"""Mutation queue — "Chimera proposes, the operator disposes."

Per ADR 0003 §"Mutation queue: adopted with simplified policy" — at MVP
the operator is a human at the CLI. Each row is a proposal Chimera made
that the operator decides whether to apply.

Statuses:
  - ``pending``  — created, awaiting operator
  - ``approved`` — operator approved; mutation runner will apply
  - ``rejected`` — operator declined
  - ``applied``  — successfully applied (handler updated config / activated skill / ...)
  - ``expired``  — pending too long (sweep_stale)
  - ``failed``   — approved but application errored
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mutation:
    id: int
    type: str
    payload: dict[str, Any]
    status: str
    reason: str | None
    created_at: str
    approved_at: str | None
    applied_at: str | None
    # v4.19: bumped by adaptation._already_proposed when a duplicate fires.
    # 0 means "seen exactly once".
    recurrence_count: int = 0


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _row_to_mutation(row: sqlite3.Row) -> Mutation:
    # ``row`` is a sqlite3.Row; column access via dict-style. The
    # recurrence_count column may not exist on a very old DB that
    # somehow skipped init_schema migration — default to 0 in that case.
    keys = row.keys() if hasattr(row, "keys") else ()
    return Mutation(
        id=row["id"],
        type=row["type"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        status=row["status"],
        reason=row["reason"],
        created_at=row["created_at"],
        approved_at=row["approved_at"],
        applied_at=row["applied_at"],
        recurrence_count=row["recurrence_count"] if "recurrence_count" in keys else 0,
    )


def create_mutation(
    conn: sqlite3.Connection,
    *,
    type: str,
    payload: dict[str, Any],
    reason: str | None = None,
) -> Mutation:
    # v4.71 (ADR 0090): proposer-scoring gate. Refuse to enqueue when
    # the proposer is in degraded/paused state — the operator has to
    # `chimera proposers promote <type>` first.
    from ..core.proposer_scoring import ProposerDegradedError, check_can_propose

    allow, deny_reason = check_can_propose(conn, type)
    if not allow:
        raise ProposerDegradedError(type, deny_reason)

    cursor = conn.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES (?, ?, 'pending', ?, ?)",
        (type, json.dumps(payload, sort_keys=True), reason, _utc_now_iso()),
    )
    row = conn.execute(
        "SELECT * FROM mutations WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_mutation(row)


def get_mutation(conn: sqlite3.Connection, mid: int) -> Mutation | None:
    row = conn.execute("SELECT * FROM mutations WHERE id = ?", (mid,)).fetchone()
    return _row_to_mutation(row) if row else None


def list_mutations(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    type: str | None = None,
    limit: int = 100,
) -> list[Mutation]:
    sql = "SELECT * FROM mutations"
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if type is not None:
        clauses.append("type = ?")
        params.append(type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [_row_to_mutation(r) for r in conn.execute(sql, params).fetchall()]


def approve_mutation(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    """Operator approves a pending mutation. Idempotent for already-approved."""
    m = get_mutation(conn, mid)
    if m is None:
        raise ValueError(f"unknown mutation: {mid}")
    if m.status not in ("pending", "approved"):
        raise ValueError(f"mutation {mid} is {m.status!r}; cannot approve")
    conn.execute(
        "UPDATE mutations SET status = 'approved', approved_at = ?, reason = ? "
        "WHERE id = ?",
        (_utc_now_iso(), reason or m.reason, mid),
    )
    return get_mutation(conn, mid)


def reject_mutation(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    m = get_mutation(conn, mid)
    if m is None:
        raise ValueError(f"unknown mutation: {mid}")
    if m.status not in ("pending",):
        raise ValueError(f"mutation {mid} is {m.status!r}; cannot reject")
    conn.execute(
        "UPDATE mutations SET status = 'rejected', reason = ? WHERE id = ?",
        (reason or m.reason, mid),
    )
    out = get_mutation(conn, mid)
    _reeval_proposer(conn, out)
    return out


def mark_applied(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    conn.execute(
        "UPDATE mutations SET status = 'applied', applied_at = ?, reason = ? "
        "WHERE id = ?",
        (_utc_now_iso(), reason, mid),
    )
    m = get_mutation(conn, mid)
    _reeval_proposer(conn, m)
    return m


def mark_failed(
    conn: sqlite3.Connection, mid: int, *, reason: str
) -> Mutation:
    conn.execute(
        "UPDATE mutations SET status = 'failed', reason = ? WHERE id = ?",
        (reason, mid),
    )
    m = get_mutation(conn, mid)
    _reeval_proposer(conn, m)
    return m


def _reeval_proposer(conn: sqlite3.Connection, m: Mutation | None) -> None:
    """v4.71 (ADR 0090): after a terminal state transition, recompute the
    proposer acceptance rate so the next ``create_mutation`` sees the
    updated status. Best-effort; never blocks the underlying write."""
    if m is None:
        return
    try:
        from ..core.proposer_scoring import evaluate_and_update
        evaluate_and_update(conn, m.type)
    except Exception:  # noqa: BLE001
        pass


def bump_recurrence(conn: sqlite3.Connection, mid: int) -> Mutation | None:
    """v4.19: record that a duplicate-signature proposal was suppressed.

    Increments the existing row's ``recurrence_count`` rather than
    enqueueing a new row, so the operator sees "this hit 8 times"
    instead of 8 separate pending mutations.
    """
    m = get_mutation(conn, mid)
    if m is None:
        return None
    conn.execute(
        "UPDATE mutations SET recurrence_count = recurrence_count + 1 "
        "WHERE id = ?",
        (mid,),
    )
    return get_mutation(conn, mid)


def queue_health(conn: sqlite3.Connection) -> dict[str, Any]:
    """v4.19: queue-health snapshot for the dashboard and CLI.

    Returns a single dict with:
      - ``counts``: status → row count
      - ``pending_oldest_age_seconds``: int | None
      - ``pending_recurrence_max``: highest recurrence_count among pending
      - ``pending_recurrence_total``: sum of recurrence_count among pending
      - ``approved_ratio``: applied / (approved + applied + rejected + failed)
        — operator signal/noise. None if no decisions yet.
    """
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM mutations GROUP BY status"
    ).fetchall()
    counts: dict[str, int] = {r["status"]: int(r["n"]) for r in rows}

    oldest = conn.execute(
        "SELECT MIN(created_at) AS oldest FROM mutations WHERE status = 'pending'"
    ).fetchone()
    pending_oldest_age: int | None = None
    if oldest and oldest["oldest"]:
        try:
            t0 = dt.datetime.fromisoformat(oldest["oldest"])
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=dt.timezone.utc)
            age = (dt.datetime.now(dt.timezone.utc) - t0).total_seconds()
            pending_oldest_age = int(age)
        except ValueError:
            pending_oldest_age = None

    rec = conn.execute(
        "SELECT COALESCE(MAX(recurrence_count), 0) AS rmax, "
        "COALESCE(SUM(recurrence_count), 0) AS rsum "
        "FROM mutations WHERE status = 'pending'"
    ).fetchone()

    decided = (
        counts.get("approved", 0)
        + counts.get("applied", 0)
        + counts.get("rejected", 0)
        + counts.get("failed", 0)
    )
    if decided > 0:
        approved_ratio: float | None = (
            counts.get("applied", 0) / decided
        )
    else:
        approved_ratio = None

    return {
        "counts": counts,
        "pending_oldest_age_seconds": pending_oldest_age,
        "pending_recurrence_max": int(rec["rmax"]) if rec else 0,
        "pending_recurrence_total": int(rec["rsum"]) if rec else 0,
        "approved_ratio": approved_ratio,
    }


def sweep_stale(
    conn: sqlite3.Connection, *, older_than_cycles: int, current_cycle: int
) -> int:
    """Expire pending mutations that have been around too long.

    Returns the count expired. Per Reggio HOUSEKEEPING phase semantics —
    "stale" is measured here in plain ISO timestamps for simplicity (one
    cycle ≈ 15min default; older_than_cycles*15min wall-clock).
    """
    cutoff_minutes = older_than_cycles * 15
    cutoff = (
        dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(minutes=cutoff_minutes)
    ).isoformat(timespec="seconds")
    cursor = conn.execute(
        "UPDATE mutations SET status = 'expired' "
        "WHERE status = 'pending' AND created_at < ?",
        (cutoff,),
    )
    return cursor.rowcount
