"""v4.71 (ADR 0090, P3): proposer acceptance-rate scoring → demotion.

The post-mortem (2026-05-20) named low proposer signal-to-noise as the
third foundational gap: skill_proposal at 62.5% noise, config_change at
60% approval. This module computes a rolling per-proposer acceptance
rate from the mutations table and persists a ``proposer_status`` row
when the rate falls below the threshold.

A demoted proposer can still *fire* (engines still write to chronicle),
but ``create_mutation`` refuses with ``ProposerDegradedError`` so no new
noise reaches the queue. The operator clears it with
``chimera proposers promote <type>``.

Design notes
------------
* "Proposer" = ``mutations.type``. The post-mortem talks about
  per-engine scoring, but engines proper (Discovery / Curiosity /
  Reflection) don't emit mutations directly. The actual proposers are
  skill_proposal, task_split, config_change, etc. — and these are
  what the operator decides on. Score them.
* Counting policy:
    accepted = applied                    (approved-but-not-yet-applied
                                           is ambiguous; we count the
                                           terminal state)
    rejected = rejected + failed          (failed = "we tried, it broke" —
                                           noise from the operator's POV)
    decided  = accepted + rejected
    rate     = accepted / decided
  ``pending`` and ``expired`` are not counted as decisions.
* Threshold default 50% over a window of the last 10 decisions. Both
  configurable via env (``CHIMERA_PROPOSER_SCORE_THRESHOLD``,
  ``CHIMERA_PROPOSER_SCORE_WINDOW``) and per-proposer env
  (``CHIMERA_PROPOSER_<TYPE>_THRESHOLD`` overrides the global).
* Master switch ``CHIMERA_PROPOSER_SCORING_ENABLED=1`` (default ON).
  When off, ``check_can_propose`` always allows and
  ``evaluate_and_update`` is a no-op.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from dataclasses import dataclass


# Default policy.
DEFAULT_THRESHOLD: float = 0.5
DEFAULT_WINDOW: int = 10


class ProposerDegradedError(RuntimeError):
    """Raised when a degraded proposer attempts ``create_mutation``."""

    def __init__(self, proposer: str, reason: str | None = None) -> None:
        self.proposer = proposer
        self.reason = reason
        super().__init__(
            f"proposer {proposer!r} is degraded"
            + (f": {reason}" if reason else "")
        )


@dataclass(frozen=True)
class ProposerScore:
    proposer: str
    accepted: int
    rejected: int
    decided: int
    rate: float | None       # None when decided == 0
    window: int              # how many recent mutations we looked at

    @property
    def is_degraded(self) -> bool:
        # Conservative: not enough data → not degraded.
        if self.rate is None:
            return False
        return self.rate < _threshold_for(self.proposer)


@dataclass(frozen=True)
class ProposerStatus:
    proposer: str
    status: str               # 'active' | 'degraded' | 'paused'
    reason: str | None
    last_rate: float | None
    last_decided: int
    updated_at: str


# ── env helpers ────────────────────────────────────────────────


def scoring_enabled() -> bool:
    return os.environ.get("CHIMERA_PROPOSER_SCORING_ENABLED", "1") not in ("0", "false", "False")


def _window() -> int:
    raw = os.environ.get("CHIMERA_PROPOSER_SCORE_WINDOW")
    if not raw:
        return DEFAULT_WINDOW
    try:
        n = int(raw)
        return n if n > 0 else DEFAULT_WINDOW
    except ValueError:
        return DEFAULT_WINDOW


def _threshold_for(proposer: str) -> float:
    # Per-proposer override.
    key = f"CHIMERA_PROPOSER_{proposer.upper()}_THRESHOLD"
    raw = os.environ.get(key) or os.environ.get("CHIMERA_PROPOSER_SCORE_THRESHOLD")
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return DEFAULT_THRESHOLD


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ── scoring ────────────────────────────────────────────────────


def compute_score(
    db: sqlite3.Connection, proposer: str, *, window: int | None = None
) -> ProposerScore:
    """Compute the acceptance rate over the last ``window`` decided rows."""
    n = window if window is not None else _window()
    # Pull the last N rows for this type that reached a decision.
    rows = db.execute(
        "SELECT status FROM mutations "
        "WHERE type = ? AND status IN ('applied','rejected','failed') "
        "ORDER BY id DESC LIMIT ?",
        (proposer, n),
    ).fetchall()
    accepted = sum(1 for r in rows if r["status"] == "applied")
    rejected = sum(1 for r in rows if r["status"] in ("rejected", "failed"))
    decided = accepted + rejected
    rate = (accepted / decided) if decided > 0 else None
    return ProposerScore(
        proposer=proposer,
        accepted=accepted,
        rejected=rejected,
        decided=decided,
        rate=rate,
        window=n,
    )


def all_proposer_types(db: sqlite3.Connection) -> list[str]:
    rows = db.execute(
        "SELECT DISTINCT type FROM mutations ORDER BY type"
    ).fetchall()
    return [r["type"] for r in rows]


def all_scores(db: sqlite3.Connection) -> list[ProposerScore]:
    return [compute_score(db, t) for t in all_proposer_types(db)]


# ── status persistence ─────────────────────────────────────────


def _row_to_status(row: sqlite3.Row) -> ProposerStatus:
    return ProposerStatus(
        proposer=row["proposer"],
        status=row["status"],
        reason=row["reason"],
        last_rate=row["last_rate"],
        last_decided=row["last_decided"] or 0,
        updated_at=row["updated_at"],
    )


def get_status(db: sqlite3.Connection, proposer: str) -> ProposerStatus | None:
    row = db.execute(
        "SELECT * FROM proposer_status WHERE proposer = ?", (proposer,)
    ).fetchone()
    return _row_to_status(row) if row else None


def list_statuses(db: sqlite3.Connection) -> list[ProposerStatus]:
    rows = db.execute(
        "SELECT * FROM proposer_status ORDER BY proposer"
    ).fetchall()
    return [_row_to_status(r) for r in rows]


def _upsert_status(
    db: sqlite3.Connection,
    *,
    proposer: str,
    status: str,
    reason: str | None,
    last_rate: float | None,
    last_decided: int,
) -> ProposerStatus:
    db.execute(
        "INSERT INTO proposer_status (proposer, status, reason, last_rate, "
        "last_decided, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(proposer) DO UPDATE SET "
        "status=excluded.status, reason=excluded.reason, "
        "last_rate=excluded.last_rate, last_decided=excluded.last_decided, "
        "updated_at=excluded.updated_at",
        (proposer, status, reason, last_rate, last_decided, _utc_now_iso()),
    )
    return get_status(db, proposer)  # type: ignore[return-value]


def evaluate_and_update(
    db: sqlite3.Connection, proposer: str
) -> tuple[ProposerScore, ProposerStatus | None]:
    """Recompute score for ``proposer`` and update ``proposer_status``.

    If the proposer is currently ``paused`` (operator-set), nothing
    changes — paused is sticky until explicit promote.

    Returns the score and the (possibly updated) status row.
    """
    score = compute_score(db, proposer)
    existing = get_status(db, proposer)

    if existing and existing.status == "paused":
        return score, existing

    if not scoring_enabled():
        return score, existing

    threshold = _threshold_for(proposer)
    if score.rate is not None and score.rate < threshold:
        reason = (
            f"acceptance {score.accepted}/{score.decided} = "
            f"{score.rate:.0%} < {threshold:.0%} over window={score.window}"
        )
        status = _upsert_status(
            db,
            proposer=proposer,
            status="degraded",
            reason=reason,
            last_rate=score.rate,
            last_decided=score.decided,
        )
        return score, status

    # Recovered: clear a stale degraded row.
    if existing and existing.status == "degraded":
        reason = (
            f"acceptance recovered to {score.accepted}/{score.decided} = "
            f"{(score.rate or 0):.0%} ≥ {threshold:.0%}"
        )
        status = _upsert_status(
            db,
            proposer=proposer,
            status="active",
            reason=reason,
            last_rate=score.rate,
            last_decided=score.decided,
        )
        return score, status

    return score, existing


def check_can_propose(db: sqlite3.Connection, proposer: str) -> tuple[bool, str | None]:
    """Gate that ``create_mutation`` calls. Returns (allow, reason).

    v4.73 (post 2026-05-20 long-cycle finding): when no status row exists
    we run ``evaluate_and_update`` opportunistically. ADR 0090's original
    design only persisted status on terminal mutation transitions — so a
    proposer that was already below threshold at v4.71 install time
    stayed silently "active" because no transition had fired the hook.
    This makes the gate honest on first read.
    """
    if not scoring_enabled():
        return True, None
    st = get_status(db, proposer)
    if st is None:
        # Backfill on first check. Best-effort: any scoring error
        # leaves us in the conservative-allow default.
        try:
            _score, st = evaluate_and_update(db, proposer)
        except Exception:  # noqa: BLE001
            return True, None
    if st is None or st.status == "active":
        return True, None
    return False, st.reason or f"proposer is {st.status}"


def promote(
    db: sqlite3.Connection, proposer: str, *, reason: str | None = None
) -> ProposerStatus:
    """Operator action: restore a degraded/paused proposer to active."""
    return _upsert_status(
        db,
        proposer=proposer,
        status="active",
        reason=reason or "operator promote",
        last_rate=None,
        last_decided=0,
    )


def pause(
    db: sqlite3.Connection, proposer: str, *, reason: str | None = None
) -> ProposerStatus:
    """Operator action: explicitly pause a proposer (sticky until promote)."""
    return _upsert_status(
        db,
        proposer=proposer,
        status="paused",
        reason=reason or "operator pause",
        last_rate=None,
        last_decided=0,
    )
