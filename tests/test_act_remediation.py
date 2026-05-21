"""v4.84 (ADR 0097) — post-escalation remediation hint tests.

Soak v5 found that scope_evasion/artifact_missing/ungrounded_citation
fire on attempt 1 but attempts 2-3 receive no diagnosis — the model
retries the same approach and burns max output tokens on analysis.
These tests pin the recovery-layer behaviour:

  - prior scope_evasion → next attempt's prompt names the expected path
  - prior artifact_missing → next attempt names the missing artifact
  - prior ungrounded_citation → next attempt names the source files
  - 3 prior failures → ActExecutor returns SKIPPED_THREE_STRIKES and
    writes an operator-visible chronicle warning
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import record_failure
from chimera.core.remediation import (
    SKIPPED_THREE_STRIKES,
    THREE_STRIKES_THRESHOLD,
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


# ── derive_remediation_hint ──────────────────────────────────


def test_derive_hint_scope_evasion_names_single_path():
    task = "Write a regression test in `tests/test_loop_guard.py` to cover X"
    hint = derive_remediation_hint(task, "scope_evasion")
    assert hint is not None
    assert "tests/test_loop_guard.py" in hint
    assert "code_exec" in hint
    # Must tell the model not to analyse.
    assert "analyse" in hint.lower() or "analysis" in hint.lower() or "write" in hint.lower()


def test_derive_hint_scope_evasion_lists_multiple_paths():
    task = (
        "Patch `chimera/tools/loop_guard.py` and add a test in "
        "`tests/test_loop_guard.py`"
    )
    hint = derive_remediation_hint(task, "scope_evasion")
    assert hint is not None
    assert "chimera/tools/loop_guard.py" in hint
    assert "tests/test_loop_guard.py" in hint


def test_derive_hint_artifact_missing_names_path():
    task = "Write the synthesis to `mind/research/foo.md` after reading sources"
    hint = derive_remediation_hint(task, "artifact_missing")
    assert hint is not None
    assert "mind/research/foo.md" in hint


def test_derive_hint_ungrounded_citation_names_source_file():
    task = (
        "Read `chimera/tools/loop_guard.py` and write a synthesis citing "
        "specific function names."
    )
    hint = derive_remediation_hint(task, "ungrounded_citation")
    assert hint is not None
    assert "chimera/tools/loop_guard.py" in hint
    assert "verbatim" in hint.lower() or "appear" in hint.lower()


def test_derive_hint_returns_none_for_non_actionable_reasons():
    task = "anything substantial here for tokens"
    for r in ("cost_cap", "rolling_hour_cap", "task_budget",
              "provider_unavailable", "stop"):
        assert derive_remediation_hint(task, r) is None


def test_derive_hint_generic_for_unknown_finish_reason():
    task = "Write a regression test in `tests/test_loop_guard.py`"
    hint = derive_remediation_hint(task, "weird_reason_xyz")
    assert hint is not None
    assert "weird_reason_xyz" in hint


def test_derive_hint_max_rounds_pushes_tool_first():
    task = "Write a synthesis to mind/research/x.md"
    hint = derive_remediation_hint(task, "max_rounds")
    assert hint is not None
    assert "tool" in hint.lower() or "code_exec" in hint or "write" in hint.lower()


# ── matching_escalations ────────────────────────────────────


def test_matching_escalations_returns_only_same_signature(db):
    record_failure(
        db, task_text="Patch chimera/tools/loop_guard.py with regression test",
        tier="haiku", finish_reason="scope_evasion", rounds_used=6, cycle=1,
    )
    record_failure(
        db, task_text="Build the agonistic futures world model",
        tier="haiku", finish_reason="max_rounds", rounds_used=20, cycle=2,
    )
    rows = matching_escalations(
        db, task_text="Patch chimera/tools/loop_guard.py with regression test",
    )
    assert len(rows) == 1
    assert rows[0].finish_reason == "scope_evasion"


def test_matching_escalations_most_recent_first(db):
    task = "Patch chimera/tools/loop_guard.py with regression test"
    record_failure(db, task_text=task, tier="haiku",
                   finish_reason="scope_evasion", rounds_used=6, cycle=1)
    record_failure(db, task_text=task, tier="sonnet",
                   finish_reason="length", rounds_used=20, cycle=2)
    rows = matching_escalations(db, task_text=task)
    assert [r.finish_reason for r in rows] == ["length", "scope_evasion"]


# ── build_remediation_preamble ──────────────────────────────


def test_preamble_empty_with_no_escalations():
    assert build_remediation_preamble([], "any task text") == ""


def test_preamble_includes_hint_and_attempt_marker(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    record_failure(db, task_text=task, tier="haiku",
                   finish_reason="scope_evasion", rounds_used=6, cycle=1)
    rows = matching_escalations(db, task_text=task)
    preamble = build_remediation_preamble(rows, task)
    assert preamble.startswith("<!--")
    assert "scope_evasion" in preamble
    assert "tests/test_loop_guard.py" in preamble
    # First-strike preamble: no "final retry" sternness yet.
    assert "final retry" not in preamble.lower()


def test_preamble_third_attempt_adds_sternness(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    for cycle, reason in [(1, "scope_evasion"), (2, "length")]:
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason=reason, rounds_used=10, cycle=cycle)
    rows = matching_escalations(db, task_text=task)
    preamble = build_remediation_preamble(rows, task)
    assert "final retry" in preamble.lower()
    assert "MUST" in preamble


# ── remediation_decision: end-to-end through the DB ────────


def test_decision_no_priors_is_noop(db):
    d = remediation_decision(db, task_text="A brand-new task body here")
    assert d.skip is False
    assert d.preamble == ""
    assert d.matched_failures == 0


def test_decision_one_prior_produces_hint(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    record_failure(db, task_text=task, tier="haiku",
                   finish_reason="scope_evasion", rounds_used=6, cycle=1)
    d = remediation_decision(db, task_text=task)
    assert d.skip is False
    assert d.matched_failures == 1
    assert "tests/test_loop_guard.py" in d.preamble


def test_decision_three_priors_triggers_skip(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    for i in range(THREE_STRIKES_THRESHOLD):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason="scope_evasion", rounds_used=6, cycle=i)
    d = remediation_decision(db, task_text=task)
    assert d.skip is True
    assert d.matched_failures == THREE_STRIKES_THRESHOLD
    assert d.preamble == ""


# ── chronicle_warning_body ──────────────────────────────────


def test_chronicle_warning_body_includes_reasons_and_action(db):
    task = "Write a regression test in `tests/test_loop_guard.py`"
    for i, r in enumerate(["scope_evasion", "length", "length"]):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason=r, rounds_used=10, cycle=i)
    rows = matching_escalations(db, task_text=task)
    body = chronicle_warning_body(task, rows)
    assert "auto-skipped" in body
    assert "scope_evasion" in body and "length" in body
    assert "operator" in body.lower() or "INBOX" in body


# ── ActExecutor integration: three-strikes short-circuit ───


class _RecordingChronicle:
    """Minimal stand-in for ChronicleManager used in unit tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert_section(self, *, section_name: str, body: str,
                       day: str | None = None) -> None:
        self.calls.append(
            {"section_name": section_name, "body": body, "day": day}
        )


@pytest.mark.asyncio
async def test_act_executor_skips_after_three_strikes(db, monkeypatch):
    """ActExecutor.execute() with 3 prior same-signature failures returns
    SKIPPED_THREE_STRIKES without calling the provider, and writes a
    chronicle warning."""
    from chimera.core.act import ActExecutor
    from chimera.tools import Dispatcher
    from chimera.tools.registry import ToolRegistry

    task = "Write a regression test in `tests/test_loop_guard.py`"
    for i in range(THREE_STRIKES_THRESHOLD):
        record_failure(db, task_text=task, tier="haiku",
                       finish_reason="scope_evasion", rounds_used=6, cycle=i)

    chronicle = _RecordingChronicle()
    executor = ActExecutor(
        dispatcher=Dispatcher(ToolRegistry()),
        providers={},  # would explode if we actually called the provider
        db=db,
        tier="haiku",
        chronicle=chronicle,
    )

    result = await executor.execute(task, cycle=99)

    assert result.completed is False
    assert result.finish_reason == SKIPPED_THREE_STRIKES
    assert result.rounds == 0
    assert chronicle.calls, "expected an upsert_section call on three-strikes"
    assert chronicle.calls[0]["section_name"] == "Escalation Warnings"
    assert "tests/test_loop_guard.py" in chronicle.calls[0]["body"] or \
           "auto-skipped" in chronicle.calls[0]["body"]


@pytest.mark.asyncio
async def test_act_executor_skip_does_not_record_new_escalation(db):
    """SKIPPED_THREE_STRIKES must not be in ESCALATING_FINISH_REASONS,
    otherwise the counter ratchets up forever."""
    from chimera.core.escalation import ESCALATING_FINISH_REASONS
    assert SKIPPED_THREE_STRIKES not in ESCALATING_FINISH_REASONS
