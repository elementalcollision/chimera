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

from .act import (
    _CHIMERA_SOURCE_PATH_PATTERN,
    _FIX_WITHOUT_TEST_EXCLUDED_SOURCES,
    expected_artifacts,
    expected_content_markers,
    intended_code_paths,
)
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


def _fix_without_test_hint(task_text: str) -> str:
    """v4.90 (ADR 0099): the soak v6 gap. Agent shipped a working fix
    but skipped the regression test. Derive the corresponding test path
    from the chimera/ source path the task most plausibly names.
    """
    # Prefer paths the task explicitly named under chimera/. Fall back
    # to a generic phrasing when the task text mentions none.
    intended = [
        p for p in intended_code_paths(task_text)
        if p.startswith("chimera/")
        and p not in _FIX_WITHOUT_TEST_EXCLUDED_SOURCES
    ]
    if not intended:
        # Pull any chimera/ source path mentioned anywhere (the task may
        # reference it without our intended-path regex matching).
        for m in _CHIMERA_SOURCE_PATH_PATTERN.finditer(task_text or ""):
            p = m.group(1)
            if p in _FIX_WITHOUT_TEST_EXCLUDED_SOURCES:
                continue
            if p not in intended:
                intended.append(p)
    if intended:
        src = intended[0]
        # chimera/foo/bar.py → tests/test_bar.py (best-effort).
        stem = src.rsplit("/", 1)[-1].removesuffix(".py")
        test_path = f"tests/test_{stem}.py"
        target_clause = (
            f"Your previous attempt added code to `{src}` but didn't "
            f"write a regression test."
        )
        action_clause = (
            f"Use code_exec to create or modify `{test_path}` with at "
            f"least 3 test cases covering normal/edge/threshold "
            f"behaviour for the new function. Don't analyse — just "
            f"write the tests."
        )
    else:
        target_clause = (
            "Your previous attempt modified chimera/ source but didn't "
            "write a regression test."
        )
        action_clause = (
            "Use code_exec to create or modify the corresponding "
            "`tests/test_<module>.py` with at least 3 test cases "
            "covering normal/edge/threshold behaviour. Don't analyse — "
            "just write the tests."
        )
    return f"{target_clause} {action_clause}"


def _artifact_incomplete_hint(task_text: str) -> str:
    """v4.96 (ADR 0101): the file exists but is missing a required
    content marker the task spelled out. The remediation is mechanical
    — append the missing marker to the existing file.
    """
    markers_by_path = expected_content_markers(task_text)
    if not markers_by_path:
        return (
            "Your previous write produced the named file but it is "
            "missing a content marker the task required (e.g. a sentinel "
            "heading). Use code_exec to append the missing section. "
            "Don't analyse — just append."
        )
    # One artifact, one marker → the most actionable hint.
    items = list(markers_by_path.items())
    if len(items) == 1 and len(items[0][1]) == 1:
        path, (marker,) = items[0][0], items[0][1]
        return (
            f"Your write to `{path}` is missing the required marker "
            f"`{marker}`. Use code_exec to append the missing section. "
            f"Don't analyse — just append."
        )
    listed = "; ".join(
        f"`{path}` needs " + ", ".join(f"`{m}`" for m in markers)
        for path, markers in items
    )
    return (
        "Your previous writes are missing required content markers: "
        f"{listed}. Use code_exec to append each missing section. "
        "Don't analyse — just append."
    )


def _inbox_claim_invalid_hint(task_text: str) -> str:
    """v4.100 (ADR 0104): the agent flipped a `[ ]`→`[x]` checkbox in
    mind/INBOX.md without producing the bullet's deliverable. The
    runtime has already reverted the checkbox; the model now needs to
    actually do the work named in the task.

    The remediation hint names the missing artifact when extractable
    so the model knows the specific path to write.
    """
    from .act import _inbox_bullet_artifacts
    expected = _inbox_bullet_artifacts(task_text)
    if expected:
        if len(expected) == 1:
            return (
                f"Your INBOX checkbox flip on this task claimed completion, "
                f"but the deliverable `{expected[0]}` doesn't exist. Use "
                f"code_exec to create the missing file. Don't analyse — "
                f"just write it. The runtime has reverted the checkbox so "
                f"the runner won't act on the lie; flipping it again "
                f"without producing the file will fail the task again."
            )
        listed = ", ".join(f"`{p}`" for p in expected)
        return (
            f"Your INBOX checkbox flip on this task claimed completion, "
            f"but the deliverables don't exist: {listed}. Use code_exec to "
            f"create each missing file. Don't analyse — just write them. "
            f"The runtime has reverted the checkbox; flipping it again "
            f"without producing the files will fail the task again."
        )
    return (
        "Your INBOX checkbox flip on this task claimed completion, but "
        "the deliverable the bullet promised isn't on disk. Use code_exec "
        "to do the work the bullet describes. Don't analyse — just write. "
        "The runtime has reverted the checkbox so the runner won't act "
        "on the lie."
    )


def _syntax_invalid_hint(
    task_text: str,
    syntax_failures: list[tuple[str, str]] | None = None,
) -> str:
    """v4.101 (ADR 0105): soak v10 — agent wrote unparseable Python.

    When the detector populated ``syntax_failures`` on the prior
    ActResult, the hint names the offending paths and line errors so the
    model goes straight to the broken region. Without that detail (the
    DB-only path, where we only remember the finish_reason), the hint
    falls back to a generic "read the file and fix it" instruction.
    """
    if not syntax_failures:
        return (
            "Your write produced invalid Python syntax. Read the file, "
            "identify the structural issue, and rewrite cleanly. "
            "Don't analyse — just fix the syntax."
        )
    parts: list[str] = []
    for path, msg in syntax_failures[:3]:
        parts.append(f"`{path}`: {msg}")
    paths_section = "\n  - ".join(parts)
    return (
        f"Your write produced invalid Python syntax:\n  - {paths_section}\n\n"
        f"Read the file context around the named line, identify the "
        f"structural issue, and rewrite the affected block cleanly. "
        f"Don't analyse — just fix the syntax."
    )


def _test_claim_invalid_hint(
    task_text: str,
    test_claim_failures: list[tuple[str, str]] | None = None,
) -> str:
    """v4.113 (ADR 0113): soak v16 — agent claimed pytest had passed
    but the run actually fails on operator-side re-run.

    When the detector populated ``test_claim_failures`` (a list of
    ``(path, failure_tail)`` pairs), the hint names the offending file
    and includes a few lines of the actual failure so the model jumps
    straight to fixing the implementation. Without that detail (the
    DB-only path), the hint falls back to a generic "re-run pytest
    and read the failures" instruction.
    """
    if not test_claim_failures:
        return (
            "Your previous attempt claimed a pytest run succeeded, but "
            "re-running the named test file from the operator side "
            "produced failures. Read the failing test and the "
            "implementation it covers, identify the bug, fix the "
            "implementation (not the test), and re-run pytest. Don't "
            "claim success until pytest exits 0."
        )
    parts: list[str] = []
    for path, tail in test_claim_failures[:3]:
        snippet = tail.strip()
        parts.append(f"`{path}`:\n    {snippet}" if snippet else f"`{path}`")
    body = "\n  - ".join(parts)
    return (
        f"Your previous attempt claimed `pytest` succeeded, but "
        f"re-running it produced failures:\n  - {body}\n\n"
        f"Read the failing test and the implementation it's testing, "
        f"identify the bug, fix the IMPLEMENTATION (not the test), "
        f"and re-run pytest. Don't claim success until pytest exits 0."
    )


def _commit_message_diff_drift_hint(
    task_text: str,
    commit_message_drift_claims: list[str] | None = None,
) -> str:
    """v4.115 (ADR 0115): the [agent] commit message named paths that
    aren't in the cumulative branch diff.

    Soak v20-relaunch: the agent wrote a tests file (passing locally)
    but never ``git add``-ed it, then committed with a message body
    claiming the tests were part of the delivery. The hint names the
    missing paths so the model can either stage-and-amend or rewrite
    the message — both are correct fixes; the lie-vs-reality gap is
    what must close.
    """
    if not commit_message_drift_claims:
        return (
            "Your last commit's message named one or more paths that "
            "aren't in the branch diff. Run `git diff --name-only "
            "main..HEAD` to see what actually changed, then EITHER "
            "`git add` the missing files and amend the commit, OR "
            "rewrite the commit message so it only references files "
            "the diff carries. Don't claim work the diff doesn't show."
        )
    paths = ", ".join(f"`{p}`" for p in commit_message_drift_claims[:5])
    return (
        f"Your last commit's message named path(s) {paths} that don't "
        f"appear in `git diff --name-only main..HEAD`. Either "
        f"`git add` the missing path(s) and amend the commit, OR "
        f"rewrite the commit message so it only references files the "
        f"diff carries. The commit-message-vs-diff gap is the failure; "
        f"close it on whichever side is correct."
    )


def _provenance_claim_invalid_hint(
    task_text: str,
    provenance_claim_failures: list[str] | None = None,
) -> str:
    """v4.118 (ADR 0118): the [agent] commit message cited a version or
    ADR number that doesn't resolve against the repo.

    Soak v20-3rd: agent shipped commit e3af158 with message claiming
    ``v4.120 / ADR 0120`` when the actual platform was v4.116 and ADR
    0120 didn't exist. The hint names the bad citations so the model
    can either drop them or replace them with real numbers — the
    fabricated-authority gap is what must close.
    """
    if not provenance_claim_failures:
        return (
            "Your last commit's message cited a version or ADR number "
            "that doesn't resolve against the repo. Check the existing "
            "tags (`git tag --list`) and `docs/adr/` index, then "
            "rewrite the commit message with citations that actually "
            "exist — or drop the citation entirely. Don't fabricate "
            "version or ADR numbers to make a commit look more "
            "authoritative than it is."
        )
    cites = ", ".join(f"`{c}`" for c in provenance_claim_failures[:5])
    return (
        f"Your last commit's message cited {cites} but none of those "
        f"resolve in this repo (no matching tag, no ADR file, no "
        f"source mention). Either rewrite the commit message with "
        f"real numbers from `git tag --list` and `docs/adr/`, or drop "
        f"the citation. Fabricating version / ADR numbers to look "
        f"authoritative is the failure mode this gate closes."
    )


def _witness_rejected_hint(
    task_text: str,
    witness_concerns: list[str] | None = None,
) -> str:
    """v4.102 (ADR 0106): the witness model read your diff and rejected it.

    When the detector populated ``witness_concerns`` on the prior
    ActResult, the hint includes the first three concerns verbatim so
    the model knows exactly what to address. The DB-only path (where
    only the finish_reason survives) falls back to a generic prompt.
    """
    if not witness_concerns:
        return (
            "Your write was rejected by code-review witness. Re-read "
            "the file you wrote, look for structural defects "
            "(dangling clauses, mismatched indent, off-by-one), and "
            "rewrite. Don't analyse — just fix."
        )
    concerns_block = "\n  - ".join(witness_concerns[:3])
    return (
        f"Your code change was rejected by witness review:\n"
        f"  - {concerns_block}\n\n"
        f"Read the file, address each concern specifically, and "
        f"rewrite. Don't analyse — just fix."
    )


_COMMIT_TASK_KEYWORDS = (
    "git commit",
    "stage and commit",
    "commit your changes",
    "make a commit",
    "create a commit",
    "commit the changes",
    "[agent] prefix",
)


def _is_commit_task(task_text: str) -> bool:
    """v4.104 (ADR 0108): identify commit-style tasks for concrete-command
    remediation. Soak v12 showed the agent burning rounds reasoning about
    what to commit instead of calling ``git`` — the fix is a hint that
    spells out the exact shell invocations.

    Matches keyword phrases (case-insensitive) plus the standalone word
    ``commit`` when paired with stage/git context. Avoids matching prose
    that mentions "commit" incidentally (e.g. "commitment", "commit log").
    """
    if not task_text:
        return False
    lowered = task_text.lower()
    if any(kw in lowered for kw in _COMMIT_TASK_KEYWORDS):
        return True
    # Standalone "commit" verb at the start of the task or right after a
    # boundary word — covers "Commit your changes…", "Stage and commit".
    if "commit" in lowered and ("git" in lowered or "stage" in lowered
                                or "branch" in lowered):
        return True
    return False


_COMMIT_REMEDIATION_HINT = (
    "Your previous attempt at committing ran out of rounds without "
    "calling `git`. Run these EXACT shell commands via shell tool (do "
    "NOT analyse — just run them):\n"
    "\n"
    "  1. shell argv=[\"git\", \"status\", \"--short\"]\n"
    "  2. shell argv=[\"git\", \"add\", \"<each modified path from step 1>\"]\n"
    "     (skip files under mind/wiki/ or anything you didn't intend\n"
    "     to commit; do NOT use 'git add -A')\n"
    "  3. shell argv=[\"git\", \"commit\", \"-m\", \"[agent] <one-line subject>\"]\n"
    "  4. shell argv=[\"git\", \"log\", \"--oneline\", \"-3\"]\n"
    "     to verify the commit landed\n"
    "\n"
    "If step 3 errors with \"Please tell me who you are\", run:\n"
    "  shell argv=[\"git\", \"config\", \"user.email\", \"agent@chimera.local\"]\n"
    "  shell argv=[\"git\", \"config\", \"user.name\", \"Chimera-Agent\"]\n"
    "then retry step 3."
)


def _commit_remediation_hint(task_text: str) -> str:
    return _COMMIT_REMEDIATION_HINT


def _max_rounds_hint(task_text: str) -> str:
    if _is_commit_task(task_text):
        return _commit_remediation_hint(task_text)
    return (
        "Your previous attempt at this task exhausted its round budget "
        "without producing a deliverable. Reduce analysis prose; call "
        "the tool that performs the requested write on the very first "
        "round if possible."
    )


def _length_hint(task_text: str) -> str:
    if _is_commit_task(task_text):
        return _commit_remediation_hint(task_text)
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
    "fix_without_test": _fix_without_test_hint,
    "artifact_incomplete": _artifact_incomplete_hint,
    "inbox_claim_invalid": _inbox_claim_invalid_hint,
    "syntax_invalid": _syntax_invalid_hint,
    "test_claim_invalid": _test_claim_invalid_hint,
    "commit_message_diff_drift": _commit_message_diff_drift_hint,
    "provenance_claim_invalid": _provenance_claim_invalid_hint,
    "witness_rejected": _witness_rejected_hint,
    "max_rounds": _max_rounds_hint,
    "length": _length_hint,
    "degenerate_loop_abort": _max_rounds_hint,
    "ping_pong_abort": _max_rounds_hint,
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
