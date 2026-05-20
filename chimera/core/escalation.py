"""PR #58 escalation — write-intent miss correction prompt + one-tier-up retry.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)":

When a task that requires writes finishes without producing the expected
write_targets (silent failure or partial), inject a correction prompt and
retry one tier up the cost ladder (haiku → sonnet → opus).

This module is pure — no provider calls. The orchestrator wires the
correction prompt back into the loop.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

_TIER_ORDER: tuple[Literal["haiku", "sonnet", "opus"], ...] = ("haiku", "sonnet", "opus")


@dataclass(frozen=True)
class EscalationPlan:
    """What the ACT phase should do next."""

    correction_prompt: str
    next_tier: str          # haiku | sonnet | opus
    retry: bool             # if False, the task is marked failed and the loop continues


def next_tier_up(current_tier: str) -> str:
    """Return the next tier in the cost ladder, or stay at the top."""
    if current_tier not in _TIER_ORDER:
        return "sonnet"
    idx = _TIER_ORDER.index(current_tier)
    return _TIER_ORDER[min(idx + 1, len(_TIER_ORDER) - 1)]


def build_correction_prompt(
    task_text: str,
    expected_paths: list[str],
    actual_writes: list[str],
) -> str:
    """The PR #58 correction message injected on retry."""
    expected_block = (
        ", ".join(sorted(expected_paths)) if expected_paths else "(none extracted)"
    )
    actual_block = (
        ", ".join(sorted(actual_writes)) if actual_writes else "NOTHING was written"
    )
    return (
        "Correction required.\n"
        f"\nThe task was:\n  {task_text!r}\n"
        f"\nYou were expected to write to:\n  {expected_block}\n"
        f"\nActual writes:\n  {actual_block}\n"
        "\nThis is a silent or partial failure. Retry the task and call the "
        "appropriate write tool against each expected path. Do not respond "
        "with prose alone — every expected path must appear in your tool calls."
    )


def build_escalation_plan(
    task_text: str,
    expected_paths: list[str],
    actual_writes: list[str],
    current_tier: str,
    retries_used: int,
    max_retries: int = 1,
) -> EscalationPlan:
    """Decide what to do after a write-intent miss.

    First miss → correction prompt + one-tier-up retry.
    Subsequent miss → mark failed (the loop continues, the operator decides).
    """
    correction = build_correction_prompt(task_text, expected_paths, actual_writes)
    if retries_used >= max_retries:
        return EscalationPlan(correction_prompt=correction, next_tier=current_tier, retry=False)
    return EscalationPlan(
        correction_prompt=correction,
        next_tier=next_tier_up(current_tier),
        retry=True,
    )


# ── v4.46: persistent task-escalation memory ────────────────


# Reasons that justify escalation. ``stop`` and other clean exits don't
# enter the table at all — only the failure modes that suggest the tier
# was insufficient for the task.
ESCALATING_FINISH_REASONS = frozenset({
    "max_rounds",
    "artifact_missing",
    "degenerate_loop_abort",
})


def _signature(task_text: str) -> str:
    """Token-bag signature, sorted + comma-joined. Cheap, deterministic,
    no NLP dependencies. Drops tokens < 4 chars to skip stop-words.
    Same shape as ``chimera.core.adaptation.signature`` but stored as
    a string so it's queryable from SQL.
    """
    import re
    tokens = {
        t.lower()
        for t in re.split(r"[^a-zA-Z0-9]+", task_text or "")
        if len(t) >= 4
    }
    return ",".join(sorted(tokens))


def record_failure(
    conn: sqlite3.Connection,
    *,
    task_text: str,
    tier: str,
    finish_reason: str,
    rounds_used: int,
    cycle: int,
) -> int | None:
    """Append a task-escalation row when ACT exits without completion.

    Returns the new row id, or None if the finish_reason doesn't warrant
    recording (e.g. ``stop`` — the task succeeded).
    """
    if finish_reason not in ESCALATING_FINISH_REASONS:
        return None
    sig = _signature(task_text)
    if not sig:
        return None
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    try:
        cur = conn.execute(
            "INSERT INTO task_escalations "
            "(signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig, task_text, tier, finish_reason, rounds_used, cycle, now),
        )
        return int(cur.lastrowid)
    except sqlite3.OperationalError:
        # Table missing — graceful no-op for pre-migration DBs.
        logger.exception("task_escalations table missing; skipping record_failure")
        return None


def recommended_tier(
    conn: sqlite3.Connection,
    *,
    task_text: str,
    default_tier: str = "haiku",
    overlap_threshold: float = 0.5,
) -> str:
    """Return the tier ACT should start at for ``task_text``.

    Walks ``task_escalations`` for rows with a signature that overlaps
    the incoming task's signature by ≥ ``overlap_threshold`` (Jaccard).
    For every such match at tier T, we promote one rung. So:

      - 0 prior failures      → default_tier
      - 1 prior haiku failure → sonnet
      - 1 prior sonnet failure → opus
      - any prior opus failure → opus (top of ladder)

    Bound: never below ``default_tier``; never above ``opus``.
    """
    incoming = _signature(task_text)
    if not incoming:
        return default_tier
    incoming_set = set(incoming.split(","))
    try:
        rows = conn.execute(
            "SELECT signature, tier FROM task_escalations"
        ).fetchall()
    except sqlite3.OperationalError:
        return default_tier

    matched_tiers: list[str] = []
    for r in rows:
        existing = set((r["signature"] or "").split(","))
        if not existing:
            continue
        union = incoming_set | existing
        if not union:
            continue
        overlap = len(incoming_set & existing) / len(union)
        if overlap >= overlap_threshold:
            matched_tiers.append(r["tier"])
    if not matched_tiers:
        return default_tier

    # Highest tier we previously failed at → start one above that.
    rank = {t: i for i, t in enumerate(_TIER_ORDER)}
    worst_failed_idx = max(
        (rank.get(t, -1) for t in matched_tiers), default=-1
    )
    if worst_failed_idx < 0:
        return default_tier
    next_idx = min(worst_failed_idx + 1, len(_TIER_ORDER) - 1)
    return _TIER_ORDER[next_idx]


# ── v4.48: operator readers ──────────────────────────────────


@dataclass(frozen=True)
class EscalationRow:
    id: int
    signature: str
    task_text: str
    tier: str
    finish_reason: str
    rounds_used: int
    cycle: int
    created_at: str


def list_escalations(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    signature_substring: str | None = None,
) -> list[EscalationRow]:
    """Most-recent-first list of escalations. Optional substring filter
    on the signature for quick "what's been failing about ``foo``"."""
    sql = "SELECT id, signature, task_text, tier, finish_reason, rounds_used, cycle, created_at FROM task_escalations"
    params: list[object] = []
    if signature_substring:
        sql += " WHERE signature LIKE ?"
        params.append(f"%{signature_substring}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        EscalationRow(
            id=int(r["id"]),
            signature=r["signature"],
            task_text=r["task_text"],
            tier=r["tier"],
            finish_reason=r["finish_reason"],
            rounds_used=int(r["rounds_used"]),
            cycle=int(r["cycle"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def escalation_summary(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Aggregate counts: signature → {tier: count}.

    Useful for spotting tasks that have failed at multiple tiers
    (they're the candidates for being genuinely hard vs noisy).
    """
    try:
        rows = conn.execute(
            "SELECT signature, tier, COUNT(*) AS n FROM task_escalations "
            "GROUP BY signature, tier"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["signature"], {})[r["tier"]] = int(r["n"])
    return out


def clear_escalations(
    conn: sqlite3.Connection,
    *,
    signature_substring: str | None = None,
) -> int:
    """Delete escalation rows. Returns the row count deleted."""
    try:
        if signature_substring:
            cur = conn.execute(
                "DELETE FROM task_escalations WHERE signature LIKE ?",
                (f"%{signature_substring}%",),
            )
        else:
            cur = conn.execute("DELETE FROM task_escalations")
        return cur.rowcount or 0
    except sqlite3.OperationalError:
        return 0
