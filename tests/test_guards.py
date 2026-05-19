"""Tests for ACT-phase guards (loop_guard, write_intent, escalation)."""

from __future__ import annotations

import pytest

from chimera.core.escalation import (
    build_correction_prompt,
    build_escalation_plan,
    next_tier_up,
)
from chimera.tools.loop_guard import (
    LoopVerdict,
    ToolCall,
    detect_degenerate_loop,
    normalize_tool_input,
)
from chimera.tools.write_intent import (
    extract_target_paths,
    requires_write_intent,
    silent_failure,
    write_intent_satisfied,
)


# ── detect_degenerate_loop ──────────────────────────────────


def test_loop_empty_history_is_ok():
    assert detect_degenerate_loop([]) is LoopVerdict.OK


def test_loop_varied_history_is_ok():
    history = [
        ToolCall("shell", {"argv": ["ls"]}),
        ToolCall("shell", {"argv": ["cat", "a.md"]}),
        ToolCall("shell", {"argv": ["ls"]}),
    ]
    assert detect_degenerate_loop(history) is LoopVerdict.OK


def test_loop_warns_at_three_consecutive():
    call = ToolCall("shell", {"argv": ["ls"]})
    assert detect_degenerate_loop([call, call, call]) is LoopVerdict.WARN


def test_loop_aborts_at_five_consecutive():
    call = ToolCall("shell", {"argv": ["ls"]})
    assert detect_degenerate_loop([call] * 5) is LoopVerdict.ABORT


def test_loop_different_args_resets_counter():
    a = ToolCall("shell", {"argv": ["ls"]})
    b = ToolCall("shell", {"argv": ["cat", "x"]})
    # 4 As, then a B, then 2 As → only 2 trailing consecutive.
    history = [a, a, a, a, b, a, a]
    assert detect_degenerate_loop(history) is LoopVerdict.OK


def test_loop_threshold_validation():
    with pytest.raises(ValueError):
        detect_degenerate_loop([ToolCall("x", {})], warn_at=1, abort_at=5)
    with pytest.raises(ValueError):
        detect_degenerate_loop([ToolCall("x", {})], warn_at=5, abort_at=3)


# ── normalize_tool_input ────────────────────────────────────


def test_normalize_none_returns_empty():
    assert normalize_tool_input(None) == {}


def test_normalize_dict_passes_through():
    args = {"argv": ["ls"], "cwd": "."}
    assert normalize_tool_input(args) == args


def test_normalize_unwraps_openrouter_raw_envelope():
    raw = {"_raw": '{"argv": ["ls"], "cwd": "."}'}
    assert normalize_tool_input(raw) == {"argv": ["ls"], "cwd": "."}


def test_normalize_unwraps_raw_with_malformed_json_returns_empty():
    raw = {"_raw": "{not valid json"}
    assert normalize_tool_input(raw) == {}


def test_normalize_parses_json_string():
    assert normalize_tool_input('{"a": 1}') == {"a": 1}


def test_normalize_json_string_that_is_not_object_returns_empty():
    assert normalize_tool_input('[1, 2, 3]') == {}


def test_normalize_garbage_returns_empty():
    assert normalize_tool_input(42) == {}
    assert normalize_tool_input("not json at all") == {}


# ── write_intent ────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Append the lesson to LESSONS.md",
        "Write a summary to mind/CHRONICLE.md",
        "Edit pyproject.toml",
        "Create state/index.json",
        "Update HEARTBEAT.md frontmatter",
        "Add a note to wiki/plans/2026.md",
    ],
)
def test_requires_write_intent_true(text):
    assert requires_write_intent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Read INBOX.md and summarize it",
        "List the files in mind/",
        "What's the cycle count?",
    ],
)
def test_requires_write_intent_false(text):
    assert not requires_write_intent(text)


def test_extract_target_paths_bare_name_gets_mind_prefix():
    paths = extract_target_paths("Append the lesson to LESSONS.md")
    assert paths == ["mind/LESSONS.md"]


def test_extract_target_paths_keeps_known_root_prefixed():
    paths = extract_target_paths("Edit mind/INBOX.md and state/foo.json")
    assert paths == ["mind/INBOX.md", "state/foo.json"]


def test_extract_target_paths_dedupes():
    paths = extract_target_paths("Append to LESSONS.md; also update LESSONS.md")
    assert paths == ["mind/LESSONS.md"]


def test_extract_target_paths_no_matches():
    assert extract_target_paths("Read the inbox") == []


def test_silent_failure_true_for_write_intent_with_no_writes():
    assert silent_failure("Append to LESSONS.md", []) is True


def test_silent_failure_false_for_read_only_task():
    assert silent_failure("Read the inbox", []) is False


def test_silent_failure_false_when_writes_occurred():
    assert silent_failure("Append to LESSONS.md", ["mind/LESSONS.md"]) is False


def test_write_intent_satisfied_all_paths_present():
    assert write_intent_satisfied(
        "Append to LESSONS.md and update mind/CHRONICLE.md",
        ["mind/LESSONS.md", "mind/CHRONICLE.md"],
    )


def test_write_intent_satisfied_partial_returns_false():
    assert not write_intent_satisfied(
        "Append to LESSONS.md and update mind/CHRONICLE.md",
        ["mind/LESSONS.md"],
    )


def test_write_intent_satisfied_no_expected_paths_is_vacuously_true():
    assert write_intent_satisfied("Edit a file somewhere", [])


# ── escalation ──────────────────────────────────────────────


def test_next_tier_up_progression():
    assert next_tier_up("haiku") == "sonnet"
    assert next_tier_up("sonnet") == "opus"
    assert next_tier_up("opus") == "opus"  # caps at top
    assert next_tier_up("unknown") == "sonnet"


def test_correction_prompt_mentions_expected_and_actual():
    prompt = build_correction_prompt(
        "Append the lesson to LESSONS.md",
        ["mind/LESSONS.md"],
        [],
    )
    assert "mind/LESSONS.md" in prompt
    assert "NOTHING" in prompt
    assert "Append the lesson to LESSONS.md" in prompt


def test_escalation_first_miss_retries_one_tier_up():
    plan = build_escalation_plan(
        task_text="Append to LESSONS.md",
        expected_paths=["mind/LESSONS.md"],
        actual_writes=[],
        current_tier="haiku",
        retries_used=0,
    )
    assert plan.retry is True
    assert plan.next_tier == "sonnet"
    assert "mind/LESSONS.md" in plan.correction_prompt


def test_escalation_second_miss_marks_failed():
    plan = build_escalation_plan(
        task_text="Append to LESSONS.md",
        expected_paths=["mind/LESSONS.md"],
        actual_writes=[],
        current_tier="sonnet",
        retries_used=1,
    )
    assert plan.retry is False
    assert plan.next_tier == "sonnet"  # stays put on failure
