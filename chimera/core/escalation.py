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
    "ping_pong_abort",
    # v4.82 (ADR 0096): scope evasion — named code path went unedited.
    # v4.83 (ADR 0095): ungrounded citation in synthesis output.
    "scope_evasion",
    "ungrounded_citation",
    # v4.90 (ADR 0099): fix-without-test — agent shipped a chimera/
    # source edit but skipped the regression test. Three strikes still
    # auto-skips so soak runs don't loop forever on the same gap.
    "fix_without_test",
    # v4.99 (ADR 0103): phase-scope fix-without-test. Per-task v4.92
    # has a structural blindspot when a phase splits the fix and the
    # test across separate tasks; the cumulative branch diff is
    # checked at phase-end (soak v9 post-mortem, Failure B).
    "phase_fix_without_test",
    # v4.96 (ADR 0101): artifact_incomplete — agent wrote the named
    # file but it lacks a required content marker the task spelled out
    # in formal language (MUST contain / MUST end with / EXACTLY).
    # Distinct from artifact_missing: the file exists, it's just hollow.
    "artifact_incomplete",
    # v4.100 (ADR 0104): inbox_claim_invalid — agent flipped a
    # `[ ]` → `[x]` checkbox in mind/INBOX.md without producing the
    # deliverable the bullet promised. Soak v9 surfaced this as a new
    # failure class: INBOX is a TRUTH STATEMENT, not storage. The
    # detector also reverts the checkbox in the working tree so the
    # next cycle's runner doesn't act on the lie.
    "inbox_claim_invalid",
    # v4.101 (ADR 0105): syntax_invalid — agent wrote a *.py file that
    # fails py_compile. Soak v10 surfaced this as a brand-new failure
    # class: an incomplete `return ActResult(...)` block shipped to
    # chimera/core/act.py and the runner spun on identical SyntaxError
    # tracebacks for 13 minutes. Recoverable with a hint, so moderate
    # severity (one-tier demote) and same three-strikes path as
    # fix_without_test.
    "syntax_invalid",
    # v4.113 (ADR 0113): test_claim_invalid — the task text claimed
    # `uv run pytest tests/X.py` succeeded but an operator-side re-run
    # exits non-zero. Soak v16 (PR #5) shipped a NameError-at-runtime
    # regression with a confident "tests pass" claim. Recoverable
    # with a hint that names the failing file and pastes the first
    # failure tail; routed through the same three-strikes path as
    # syntax_invalid and fix_without_test.
    "test_claim_invalid",
    # v4.115 (ADR 0115): commit_message_diff_drift — the agent's
    # [agent] commit message named files that don't appear in the
    # cumulative diff. Soak v20-relaunch surfaced an un-git-add'd
    # tests file claimed in the message body. Recoverable with a
    # hint that names the missing paths; routed through the same
    # three-strikes auto-skip as test_claim_invalid / syntax_invalid.
    "commit_message_diff_drift",
    # v4.102 (ADR 0106): witness_rejected — a second model READ the
    # diff for a foundational code change and flagged structural,
    # correctness, or convention issues. Recoverable with a hint
    # (the witness names the concerns); routed through the same
    # three-strikes path as syntax_invalid and fix_without_test.
    "witness_rejected",
    # v4.84 (ADR 0097): the soak v5 retry pattern was scope_evasion →
    # length → length. Without recording `length`, the three-strikes
    # auto-skip never triggers and the budget burns silently. `length`
    # is a real capability signal: the model needed more output budget
    # than the tier allotted, so promotion is justified.
    "length",
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


#: v4.56 (ADR 0075): task-text keywords that signal research-shaped
#: work — multi-step citation + synthesis that haiku consistently
#: fails to complete in budget. The 2026-05-19 escalation postmortem
#: (mind/overnight/escalation-postmortem.md §"Systematic patterns")
#: identified this pattern explicitly: "research requires web_search +
#: http_fetch + citation weaving + file writing — that's 4+ tool
#: types. Haiku struggles to sequence them without exhausting rounds."
#: When ANY of these keywords appears, the floor tier becomes sonnet
#: regardless of the ``default_tier`` arg or escalation memory state.
_RESEARCH_TASK_KEYWORDS: tuple[str, ...] = (
    "peer-reviewed",
    "peer reviewed",
    "cite inline",
    "citation",
    "research and write",
    "research and synthesize",
    "research and synthesise",
    "academic literature",
    "named journalism",
)


def research_task_floor_tier(task_text: str) -> str | None:
    """Return ``"sonnet"`` if the task is research-shaped, else None.

    Pure heuristic — looks for the keyword set above in a lowered
    copy of the task text. Operators can preview this with the test
    fixtures in ``tests/test_research_tier_floor.py``.
    """
    if not task_text:
        return None
    lower = task_text.lower()
    for kw in _RESEARCH_TASK_KEYWORDS:
        if kw in lower:
            return "sonnet"
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

      - 0 prior failures      → default_tier (with research-floor lift)
      - 1 prior haiku failure → sonnet
      - 1 prior sonnet failure → opus
      - any prior opus failure → opus (top of ladder)

    v4.56 (ADR 0075): if ``task_text`` matches the research-task
    heuristic, the effective floor becomes ``sonnet`` regardless of
    the caller-supplied ``default_tier``. Saves the haiku→sonnet
    round-trip on tasks that haiku cannot complete by construction.

    Bound: never below ``default_tier`` (or the research floor,
    whichever is higher); never above ``opus``.
    """
    # v4.56: apply the research-task floor before consulting memory.
    floor = research_task_floor_tier(task_text)
    rank = {t: i for i, t in enumerate(_TIER_ORDER)}
    if floor is not None and rank.get(floor, -1) > rank.get(default_tier, -1):
        default_tier = floor

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
    worst_failed_idx = max(
        (rank.get(t, -1) for t in matched_tiers), default=-1
    )
    if worst_failed_idx < 0:
        return default_tier
    next_idx = min(worst_failed_idx + 1, len(_TIER_ORDER) - 1)
    promoted = _TIER_ORDER[next_idx]
    # v4.56: never demote below the research-task floor.
    if rank.get(promoted, -1) < rank.get(default_tier, -1):
        return default_tier
    return promoted


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


@dataclass
class HotSignature:
    """A task signature that has accumulated ≥ ``threshold`` failures.

    v4.54 (ADR 0073) — surfaced to operators because the
    escalation-postmortem analysis showed that two failures on the same
    signature is the inflection point where "tier was wrong" tips into
    "task text needs rewriting." The summary view is for routine
    inspection; this list is the *alarm* — these signatures should
    surface to the human, not silently re-attempt.
    """

    signature: str
    total_failures: int
    tiers: list[str]
    first_seen_cycle: int
    last_seen_cycle: int
    last_finish_reason: str
    excerpt: str


def hot_signatures(
    conn: sqlite3.Connection, *, threshold: int = 2,
) -> list[HotSignature]:
    """Return signatures that have failed ≥ ``threshold`` times.

    Threshold default 2 matches the escalation-postmortem heuristic.
    Sorted by total_failures desc so the worst offenders surface first.
    Empty result is the healthy state — most days will return [].
    """
    try:
        rows = conn.execute(
            "SELECT signature, "
            "  COUNT(*) AS n, "
            "  GROUP_CONCAT(DISTINCT tier) AS tiers, "
            "  MIN(cycle) AS first_cycle, "
            "  MAX(cycle) AS last_cycle "
            "FROM task_escalations "
            "GROUP BY signature "
            "HAVING n >= ? "
            "ORDER BY n DESC, last_cycle DESC",
            (threshold,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[HotSignature] = []
    for r in rows:
        sig = r["signature"]
        # Pull the most recent row for excerpt + finish_reason context.
        detail = conn.execute(
            "SELECT finish_reason, task_text FROM task_escalations "
            "WHERE signature = ? ORDER BY cycle DESC LIMIT 1",
            (sig,),
        ).fetchone()
        finish_reason = detail["finish_reason"] if detail else ""
        task_text = detail["task_text"] if detail else ""
        excerpt = task_text[:120].replace("\n", " ") if task_text else ""
        tiers_csv = r["tiers"] or ""
        out.append(HotSignature(
            signature=sig,
            total_failures=int(r["n"]),
            tiers=sorted(set(tiers_csv.split(","))) if tiers_csv else [],
            first_seen_cycle=int(r["first_cycle"]),
            last_seen_cycle=int(r["last_cycle"]),
            last_finish_reason=finish_reason or "",
            excerpt=excerpt,
        ))
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


def prune_escalations(conn: sqlite3.Connection, max_age_days: int) -> int:
    """Delete escalation rows older than ``max_age_days``.

    Returns the number of rows deleted. ``max_age_days <= 0`` is a no-op
    (returns 0). A missing ``task_escalations`` table is also a no-op
    (returns 0 with a logged warning).
    """
    if max_age_days <= 0:
        return 0
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max_age_days)
    cutoff_iso = cutoff.isoformat(timespec="seconds")
    try:
        cur = conn.execute(
            "DELETE FROM task_escalations WHERE created_at < ?",
            (cutoff_iso,),
        )
        return cur.rowcount or 0
    except sqlite3.OperationalError:
        logger.exception("task_escalations table missing; prune_escalations is a no-op")
        return 0
