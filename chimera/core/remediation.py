"""v4.84 (ADR 0097) — post-escalation remediation hints.

Soak v5 (mind/postmortems/soak-v5-2026-05-20.md, finding #4) showed
that the detection layer (v4.79 artifact_missing, v4.82 scope_evasion,
v4.83 ungrounded_citation) fires correctly but the *recovery* layer is
empty: when a task escalates, the next attempt receives the same task
text without any guidance about what went wrong on the prior attempt.
The model retries the same approach and burns max output tokens on
analysis instead of switching to tool-based editing.

This module derives a short, finish-reason-specific remediation hint
from the prior failure's task_text + finish_reason, and decides when
to give up entirely (three-strikes auto-skip).

Pure functions — no DB access, no provider calls. ACT wires the lookup.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .act import expected_artifacts, intended_code_paths
from .escalation import EscalationRow, _signature
from .grounding import extract_cited_source_files


# Three strikes → permanent skip for the current cycle, with an
# operator-visible chronicle warning. Soak postmortems converge on
# 2 same-signature failures being the inflection point where "tier
# was wrong" tips into "task text needs rewriting" (ADR 0073). At 3
# we have strong evidence the model cannot make progress without
# human intervention; auto-retry is just spending budget.
THREE_STRIKES_THRESHOLD = 3

# finish_reason emitted when ACT short-circuits at three strikes.
# Not in ESCALATING_FINISH_REASONS — we do NOT want to record this
# as yet another failure, that would push the counter up forever.
SKIPPED_THREE_STRIKES = "skipped_three_strikes"


@dataclass(frozen=True)
class RemediationDecision:
    """What ACT should do given the prior-failure record for a task."""

    skip: bool                 # if True, do not call provider; record warning
    preamble: str              # text to prepend to the user message, may be ""
    matched_failures: int      # count of prior failures on this signature
    strongest: bool            # third+ strike → escalate hint sternness


def _scope_evasion_hint(task_text: str) -> str:
    paths = intended_code_paths(task_text)
    if not paths:
        return (
            "Your previous attempt at this task reported completed=True "
            "but did not edit any of the source paths the task named. "
            "Use code_exec or shell now to write/patch the named file(s) "
            "directly. Do not write a spec under mind/ in lieu of the "
            "named code path."
        )
    if len(paths) == 1:
        target = paths[0]
        return (
            f"Your previous attempt at this task reported completed=True "
            f"but did NOT write to `{target}`. Use the code_exec tool now "
            f"to create or patch that file. Don't analyse — write."
        )
    targets = ", ".join(f"`{p}`" for p in paths)
    return (
        "Your previous attempt at this task reported completed=True but "
        f"did NOT edit the named source paths: {targets}. Pick the one "
        "the task most directly names and patch it with code_exec or "
        "shell. Analysis-only responses will be rejected again."
    )


def _artifact_missing_hint(task_text: str) -> str:
    expected = expected_artifacts(task_text)
    if not expected:
        return (
            "Your previous attempt declared the task done but did not "
            "produce the expected artifact. Use code_exec or shell to "
            "write the file before declaring completion."
        )
    if len(expected) == 1:
        return (
            "Your previous attempt declared the task done but did not "
            f"produce `{expected[0]}`. Use code_exec or shell to write "
            "the file before declaring completion."
        )
    listed = ", ".join(f"`{p}`" for p in expected)
    return (
        "Your previous attempt declared the task done but the expected "
        f"artifacts were missing or empty: {listed}. Write every named "
        "path before declaring completion."
    )


def _ungrounded_citation_hint(task_text: str) -> str:
    sources = extract_cited_source_files(task_text)
    if not sources:
        return (
            "Your prior analysis cited symbols that do not exist in any "
            "source file referenced by this task. Re-read the relevant "
            "files with code_exec or shell `cat`; cite only symbols that "
            "appear verbatim in the source."
        )
    if len(sources) == 1:
        return (
            "Your prior analysis cited symbols that do not appear in "
            f"`{sources[0]}`. Re-read that file with `cat` or code_exec; "
            "cite only symbols that appear verbatim in the source."
        )
    listed = ", ".join(f"`{s}`" for s in sources)
    return (
        "Your prior analysis cited symbols that do not appear in the "
        f"source files this task references: {listed}. Re-read those "
        "files first; cite only symbols that appear verbatim."
    )


def _max_rounds_hint(task_text: str) -> str:
    return (
        "Your previous attempt at this task exhausted its round budget "
        "without producing a deliverable. Reduce analysis prose; call "
        "the tool that performs the requested write on the very first "
        "round if possible."
    )


def _length_hint(task_text: str) -> str:
    return (
        "Your previous attempt hit the output-token limit writing prose. "
        "Use code_exec or shell to perform the requested edit directly "
        "instead of describing it. The runtime rewards tool calls, not "
        "explanations."
    )


def _generic_hint(finish_reason: str) -> str:
    return (
        f"Your previous attempt at this task failed with "
        f"finish_reason={finish_reason!r}. Try a tool-first approach: "
        "call code_exec or shell on the first round."
    )


_HINT_BY_REASON = {
    "scope_evasion": _scope_evasion_hint,
    "artifact_missing": _artifact_missing_hint,
    "ungrounded_citation": _ungrounded_citation_hint,
    "max_rounds": _max_rounds_hint,
    "length": _length_hint,
    "degenerate_loop_abort": _max_rounds_hint,
}


def derive_remediation_hint(
    task_text: str, finish_reason: str,
) -> str | None:
    """Return a one-paragraph remediation hint for the prior failure.

    Returns None when ``finish_reason`` is a non-actionable exit (cost
    caps, provider errors). Returns a non-empty string otherwise.
    """
    if not finish_reason:
        return None
    if finish_reason in {
        "cost_cap", "rolling_hour_cap", "task_budget",
        "provider_unavailable", "stop",
    }:
        return None
    builder = _HINT_BY_REASON.get(finish_reason)
    if builder is None:
        return _generic_hint(finish_reason)
    return builder(task_text)


def matching_escalations(
    conn: sqlite3.Connection, *, task_text: str, limit: int = 10,
) -> list[EscalationRow]:
    """Recent escalations with the same exact signature as ``task_text``.

    Most-recent-first. Empty list when no priors exist or the task text
    has no useful tokens (signature would be empty).
    """
    sig = _signature(task_text)
    if not sig:
        return []
    try:
        rows = conn.execute(
            "SELECT id, signature, task_text, tier, finish_reason, "
            "rounds_used, cycle, created_at "
            "FROM task_escalations WHERE signature = ? "
            "ORDER BY id DESC LIMIT ?",
            (sig, limit),
        ).fetchall()
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


def build_remediation_preamble(
    escalations: list[EscalationRow], task_text: str,
) -> str:
    """Build the user-message preamble to prepend before the task text.

    On a third+ strike, escalates the hint sternness: the preamble adds
    an explicit "you MUST call a write tool; analysis-only responses
    will be rejected" clause.
    """
    if not escalations:
        return ""
    most_recent = escalations[0]
    hint = derive_remediation_hint(task_text, most_recent.finish_reason)
    if not hint:
        return ""
    strike_n = len(escalations) + 1  # this attempt's number
    header = (
        f"<!-- prior attempt {strike_n - 1} failed: "
        f"{most_recent.finish_reason} (tier={most_recent.tier}, "
        f"rounds={most_recent.rounds_used}) -->\n"
    )
    if strike_n >= THREE_STRIKES_THRESHOLD:
        sternness = (
            "\n\nThis is your final retry. You MUST call a write tool "
            "(code_exec or shell) this round; analysis-only responses "
            "will be rejected and the task will be skipped."
        )
    else:
        sternness = ""
    return f"{header}{hint}{sternness}\n\n"


def remediation_decision(
    conn: sqlite3.Connection, *, task_text: str,
) -> RemediationDecision:
    """Single entry point for ACT: returns skip-or-not + preamble.

    - 0 prior failures        → no skip, empty preamble (no-op)
    - 1 or 2 prior failures   → no skip, hint preamble
    - 3+ prior failures       → skip, no preamble (chronicle warning)
    """
    escalations = matching_escalations(conn, task_text=task_text)
    n = len(escalations)
    if n == 0:
        return RemediationDecision(
            skip=False, preamble="", matched_failures=0, strongest=False,
        )
    if n >= THREE_STRIKES_THRESHOLD:
        return RemediationDecision(
            skip=True, preamble="", matched_failures=n, strongest=True,
        )
    preamble = build_remediation_preamble(escalations, task_text)
    return RemediationDecision(
        skip=False,
        preamble=preamble,
        matched_failures=n,
        strongest=False,
    )


def chronicle_warning_body(
    task_text: str, escalations: list[EscalationRow],
) -> str:
    """Format the operator-visible chronicle entry for a three-strikes skip."""
    excerpt = (task_text or "").strip().replace("\n", " ")
    if len(excerpt) > 140:
        excerpt = excerpt[:137] + "..."
    reasons = ", ".join(e.finish_reason for e in escalations)
    return (
        f"Task auto-skipped after {len(escalations)} consecutive "
        f"failures (reasons: {reasons}).\n\n"
        f"- Task: {excerpt}\n"
        f"- Signature: `{_signature(task_text)[:80]}`\n"
        f"- Action: operator should rewrite the task text in mind/INBOX.md "
        f"or split it via the v4.65 decomposer before the next cycle."
    )
