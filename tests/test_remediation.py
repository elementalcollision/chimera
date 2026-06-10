"""Direct unit tests for chimera/core/remediation.py.

Complements the behaviour pinned elsewhere:

  - tests/test_act_remediation.py — happy-path hints, three-strikes
    skip, ActExecutor integration
  - per-detector files (test_syntax_invalid.py, test_witness_code_change.py,
    test_charter_file_count.py, ...) — detail-rich hint variants

This module covers what those miss: pure-function edge cases, fallback
branches when extraction finds nothing, malformed/empty inputs, the
commit-task classifier, DB-degradation paths (missing table, empty
signature), and formatting contracts of the preamble/chronicle body.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from chimera.core.escalation import EscalationRow, record_failure
from chimera.core.remediation import (
    THREE_STRIKES_THRESHOLD,
    _HINT_BY_REASON,
    RemediationDecision,
    _is_commit_task,
    build_remediation_preamble,
    chronicle_warning_body,
    derive_remediation_hint,
    matching_escalations,
    remediation_decision,
)
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _row(finish_reason: str = "scope_evasion", *, row_id: int = 1,
         tier: str = "haiku", rounds_used: int = 6, cycle: int = 1,
         task_text: str = "task") -> EscalationRow:
    return EscalationRow(
        id=row_id, signature="sig", task_text=task_text, tier=tier,
        finish_reason=finish_reason, rounds_used=rounds_used, cycle=cycle,
        created_at="2026-06-10T00:00:00Z",
    )


# ── _is_commit_task ─────────────────────────────────────────────────


def test_is_commit_task_empty_text_is_false():
    assert _is_commit_task("") is False


@pytest.mark.parametrize("text", [
    "Stage and commit the documentation updates.",
    "Make a commit summarising the change.",
    "Use the [agent] prefix on the message subject.",
    "Commit your changes to the current branch.",
    "Now commit the staged files with git.",
])
def test_is_commit_task_true_cases(text):
    assert _is_commit_task(text) is True


@pytest.mark.parametrize("text", [
    "Summarise the commit log conventions in a doc.",
    "Write a synthesis to mind/research/x.md",
    "Analyse the staging environment configuration.",
])
def test_is_commit_task_false_cases(text):
    assert _is_commit_task(text) is False


def test_is_commit_task_commitment_prose_is_not_a_commit_task():
    """v4.121 word-boundary fix: 'commitment' + 'git' in prose must not
    classify as a commit task (was substring-matched; xfail until fixed)."""
    text = "Demonstrate commitment to the git workflow guidelines."
    assert _is_commit_task(text) is False


@pytest.mark.parametrize("text", [
    "Investigate the branching strategy documentation.",   # 'branching' != branch ctx
    "Review uncommitted analysis notes for accuracy.",     # 'uncommitted' != commit
])
def test_is_commit_task_word_boundaries_reject_embedded_words(text):
    assert _is_commit_task(text) is False


# ── derive_remediation_hint: edges and fallback branches ───────────


def test_empty_finish_reason_returns_none():
    assert derive_remediation_hint("some task", "") is None


@pytest.mark.parametrize("reason", sorted(_HINT_BY_REASON))
def test_every_registered_reason_survives_empty_task_text(reason):
    hint = derive_remediation_hint("", reason)
    assert isinstance(hint, str)
    assert hint.strip()


@pytest.mark.parametrize("reason", ["degenerate_loop_abort", "ping_pong_abort"])
def test_loop_aborts_route_to_max_rounds_hint(reason):
    task = "Write a synthesis to mind/research/x.md"
    assert derive_remediation_hint(task, reason) == \
        derive_remediation_hint(task, "max_rounds")


def test_length_non_commit_task_mentions_token_limit():
    hint = derive_remediation_hint(
        "Write a synthesis to mind/research/x.md", "length",
    )
    assert hint is not None
    assert "output-token" in hint
    assert "git add" not in hint


def test_scope_evasion_no_named_path_falls_back_to_generic():
    hint = derive_remediation_hint(
        "Improve the loop guard behaviour.", "scope_evasion",
    )
    assert hint is not None
    assert "did not edit any of the source paths" in hint
    assert "mind/" in hint  # warns against spec-in-lieu-of-code evasion


def test_artifact_missing_no_named_artifact_falls_back_to_generic():
    hint = derive_remediation_hint("Do the needful.", "artifact_missing")
    assert hint is not None
    assert "expected artifact" in hint
    assert "`" not in hint  # nothing to name


def test_artifact_missing_lists_every_named_artifact():
    task = "Write `mind/research/a.md` and `mind/research/b.md` today."
    hint = derive_remediation_hint(task, "artifact_missing")
    assert hint is not None
    assert "mind/research/a.md" in hint
    assert "mind/research/b.md" in hint
    assert "every named" in hint


def test_ungrounded_citation_no_source_falls_back_to_generic():
    hint = derive_remediation_hint(
        "Summarise the architecture decisions.", "ungrounded_citation",
    )
    assert hint is not None
    assert "do not exist" in hint
    assert "verbatim" in hint


def test_ungrounded_citation_lists_multiple_sources():
    task = (
        "Read `chimera/core/act.py` and `chimera/core/grounding.py` "
        "then cite the helpers."
    )
    hint = derive_remediation_hint(task, "ungrounded_citation")
    assert hint is not None
    assert "chimera/core/act.py" in hint
    assert "chimera/core/grounding.py" in hint


def test_fix_without_test_skips_excluded_sources():
    task = "Patch `chimera/__init__.py` to bump the version export."
    hint = derive_remediation_hint(task, "fix_without_test")
    assert hint is not None
    # The excluded source must not derive a bogus test path.
    assert "tests/test___init__.py" not in hint
    assert "tests/test_<module>.py" in hint


# ── matching_escalations: degraded inputs ───────────────────────────


def test_matching_escalations_empty_signature_returns_empty(db):
    # All tokens < 4 chars → empty signature → no lookup at all.
    record_failure(db, task_text="Patch chimera/core/act.py edge case",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=20, cycle=1)
    assert matching_escalations(db, task_text="do it ok") == []
    assert matching_escalations(db, task_text="") == []


def test_matching_escalations_missing_table_returns_empty(tmp_path):
    bare = sqlite3.connect(tmp_path / "bare.db")
    try:
        rows = matching_escalations(
            bare, task_text="Patch chimera/core/act.py edge case",
        )
        assert rows == []
    finally:
        bare.close()


def test_matching_escalations_respects_limit(db):
    task = "Patch chimera/tools/loop_guard.py with a regression test"
    for i in range(5):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason="max_rounds", rounds_used=i, cycle=i)
    rows = matching_escalations(db, task_text=task, limit=2)
    assert len(rows) == 2
    # Most recent first → highest rounds_used values.
    assert [r.rounds_used for r in rows] == [4, 3]


def test_matching_escalations_row_field_fidelity(db):
    task = "Patch chimera/tools/loop_guard.py with a regression test"
    record_failure(db, task_text=task, tier="sonnet",
                   finish_reason="scope_evasion", rounds_used=7, cycle=42)
    (row,) = matching_escalations(db, task_text=task)
    assert row.tier == "sonnet"
    assert row.finish_reason == "scope_evasion"
    assert row.rounds_used == 7
    assert row.cycle == 42
    assert row.task_text == task


# ── build_remediation_preamble: formatting + non-actionable prior ──


def test_preamble_empty_when_prior_reason_is_non_actionable():
    rows = [_row("cost_cap")]
    assert build_remediation_preamble(rows, "any task text") == ""


def test_preamble_header_carries_attempt_tier_and_rounds():
    task = "Write a regression test in `tests/test_loop_guard.py`"
    rows = [_row("scope_evasion", tier="haiku", rounds_used=6)]
    preamble = build_remediation_preamble(rows, task)
    assert "prior attempt 1 failed" in preamble
    assert "tier=haiku" in preamble
    assert "rounds=6" in preamble
    assert preamble.endswith("\n\n")


def test_preamble_uses_most_recent_failure_for_hint():
    task = "Write a regression test in `tests/test_loop_guard.py`"
    rows = [_row("artifact_missing", row_id=2), _row("scope_evasion")]
    preamble = build_remediation_preamble(rows, task)
    assert "artifact_missing" in preamble
    assert "scope_evasion" not in preamble


# ── remediation_decision ────────────────────────────────────────────


def test_decision_two_priors_hints_without_skip(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    for i in range(2):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason="scope_evasion", rounds_used=6, cycle=i)
    d = remediation_decision(db, task_text=task)
    assert d.skip is False
    assert d.matched_failures == 2
    assert d.strongest is False
    assert d.preamble != ""


def test_decision_beyond_threshold_still_skips(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    for i in range(THREE_STRIKES_THRESHOLD + 2):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason="max_rounds", rounds_used=20, cycle=i)
    d = remediation_decision(db, task_text=task)
    assert d.skip is True
    assert d.strongest is True
    assert d.matched_failures == THREE_STRIKES_THRESHOLD + 2
    assert d.preamble == ""


def test_decision_empty_signature_task_is_noop(db):
    record_failure(db, task_text="Patch chimera/core/act.py edge case",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=20, cycle=1)
    d = remediation_decision(db, task_text="do it ok")
    assert d == RemediationDecision(
        skip=False, preamble="", matched_failures=0, strongest=False,
    )


def test_decision_missing_table_is_noop(tmp_path):
    bare = sqlite3.connect(tmp_path / "bare.db")
    try:
        d = remediation_decision(
            bare, task_text="Patch chimera/core/act.py edge case",
        )
        assert d.skip is False
        assert d.matched_failures == 0
    finally:
        bare.close()


def test_remediation_decision_is_immutable():
    d = RemediationDecision(
        skip=False, preamble="", matched_failures=0, strongest=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.skip = True  # type: ignore[misc]


# ── chronicle_warning_body: formatting contracts ────────────────────


def test_chronicle_body_truncates_long_task_and_flattens_newlines():
    task = "Line one\nLine two\n" + "x" * 200
    body = chronicle_warning_body(task, [_row("length")])
    task_line = next(
        line for line in body.splitlines() if line.startswith("- Task: ")
    )
    excerpt = task_line.removeprefix("- Task: ")
    assert "\n" not in excerpt
    assert excerpt.endswith("...")
    assert len(excerpt) == 140


def test_chronicle_body_short_task_is_not_truncated():
    task = "Write `mind/research/a.md`."
    body = chronicle_warning_body(task, [_row("length")])
    assert task in body
    assert "..." not in body.splitlines()[2]  # the "- Task:" line


def test_chronicle_body_lists_all_failure_reasons_in_order():
    rows = [_row("length", row_id=2), _row("max_rounds")]
    body = chronicle_warning_body("Patch chimera/core/act.py soon", rows)
    assert "auto-skipped after 2 consecutive" in body
    assert "length, max_rounds" in body


def test_chronicle_body_survives_empty_task_text():
    body = chronicle_warning_body("", [_row("max_rounds")])
    assert "auto-skipped after 1" in body
    assert "- Signature: ``" in body
    assert "INBOX" in body
