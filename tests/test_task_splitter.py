"""v4.63 (ADR 0082) — task splitter."""

from __future__ import annotations

import pytest

from chimera.core.task_splitter import (
    build_splitter_prompt,
    is_splittable_shape,
    parse_splitter_response,
    split_task,
)


# ── heuristic ─────────────────────────────────────────────────────


def test_empty_text_not_splittable():
    sig = is_splittable_shape("")
    assert sig.splittable is False
    assert sig.confidence == 0.0
    assert sig.reasons == []


def test_simple_one_step_not_splittable():
    sig = is_splittable_shape("Refactor the loop body in chimera/core/loop.py.")
    assert sig.splittable is False
    assert sig.confidence < 0.5


def test_numbered_sections_trigger():
    sig = is_splittable_shape(
        "Do the following: (1) Write part A. (2) Write part B. (3) Write part C."
    )
    assert sig.splittable is True
    assert "numbered sections" in " ".join(sig.reasons)


def test_explicit_multi_section_trigger():
    sig = is_splittable_shape(
        "Research and write the FOUR missing sections. Each section requires "
        "careful citation."
    )
    assert sig.splittable is True
    assert any("multi-section" in r for r in sig.reasons)


def test_spawn_n_subagents_trigger():
    sig = is_splittable_shape(
        "For this task you should spawn 14 sub-agents and have each one "
        "answer a single question, then compile the results."
    )
    assert sig.splittable is True
    assert any("sub-agents" in r for r in sig.reasons)


def test_for_each_pattern_alone_not_enough():
    """A single weak signal shouldn't trip the heuristic."""
    sig = is_splittable_shape("For each entity, log a row.")
    assert sig.splittable is False


def test_multi_artifact_strong_signal():
    sig = is_splittable_shape(
        "Write `mind/a.md`, `mind/b.md`, and `state/c.json`. "
        "For each file include a header. "
        "Then compile the results into `mind/summary.md`."
    )
    assert sig.splittable is True
    assert any("artifacts" in r for r in sig.reasons)


def test_overnight_burn_task_detected():
    """The 2026-05-19 dashboard-honesty-audit task — the canonical bad shape."""
    task = (
        "Dashboard honesty audit. For each widget listed in docs/runbook.md "
        "'What the dashboard tells you', spawn a sub-agent on "
        "openrouter/anthropic/claude-3.5-sonnet to answer ONE question: "
        "'Does this widget say what it shows, or does it imply more than "
        "it measures?' Compile the answers into "
        "`mind/overnight/widget-honesty-audit.md`."
    )
    sig = is_splittable_shape(task)
    assert sig.splittable is True
    assert sig.confidence >= 0.5


def test_four_section_research_task_detected():
    """Same shape as the overnight 4-section research task."""
    task = (
        "Research and write FOUR sections: (1) Capital as a first-class "
        "node, (2) Feedback loops, (3) Named antagonists, (4) Structural "
        "omissions. Each section requires peer-reviewed citations. "
        "Append to `mind/agonistic_futures_annotated.md` and update "
        "`mind/agonistic_futures_world_model.html`. Spawn 2 sub-agents "
        "for adversarial review."
    )
    sig = is_splittable_shape(task)
    assert sig.splittable is True
    assert sig.confidence >= 0.7


# ── prompt builder ────────────────────────────────────────────────


def test_prompt_includes_task_text():
    p = build_splitter_prompt("Refactor module X.")
    assert "Refactor module X." in p
    assert "---" in p  # the framing delimiters


# ── response parser ───────────────────────────────────────────────


def test_parse_raw_json_split_true():
    text = '{"split": true, "subtasks": ["task A", "task B", "task C"]}'
    assert parse_splitter_response(text) == ["task A", "task B", "task C"]


def test_parse_raw_json_split_false():
    text = '{"split": false, "reason": "single coherent task"}'
    assert parse_splitter_response(text) == []


def test_parse_markdown_fenced_json():
    text = '```json\n{"split": true, "subtasks": ["a", "b"]}\n```'
    assert parse_splitter_response(text) == ["a", "b"]


def test_parse_strips_empty_subtasks():
    text = '{"split": true, "subtasks": ["a", "", "  ", "b"]}'
    assert parse_splitter_response(text) == ["a", "b"]


def test_parse_malformed_returns_empty():
    assert parse_splitter_response("not json at all") == []
    assert parse_splitter_response("") == []
    assert parse_splitter_response("```json\n{not parseable\n```") == []


def test_parse_array_not_object_returns_empty():
    """Defensive: the model might emit a bare array — we want the
    object shape so we can read `split: true/false`. A bare array
    returns []."""
    assert parse_splitter_response('["a", "b", "c"]') == []


def test_parse_subtasks_not_list_returns_empty():
    text = '{"split": true, "subtasks": "should-be-a-list"}'
    assert parse_splitter_response(text) == []


# ── async split_task with a stub provider ────────────────────────


class _StubResponse:
    def __init__(self, text: str):
        self.text = text


class _StubProvider:
    """Minimal async provider that returns a canned response."""

    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call = None

    async def complete_with_tools(self, *, messages, model_id, tools, max_tokens):
        self.last_call = {
            "messages": messages, "model_id": model_id,
            "tools": tools, "max_tokens": max_tokens,
        }
        return _StubResponse(self._response_text)


@pytest.mark.asyncio
async def test_split_task_returns_subtasks_from_provider():
    provider = _StubProvider(
        '{"split": true, "subtasks": ["sub 1", "sub 2", "sub 3"]}'
    )
    subs = await split_task(
        "long bundled task with (1) and (2) and (3) parts",
        provider=provider, model_id="deepseek/deepseek-v4-pro",
    )
    assert subs == ["sub 1", "sub 2", "sub 3"]
    # Provider was called with the right model_id.
    assert provider.last_call["model_id"] == "deepseek/deepseek-v4-pro"
    # Splitter sends an empty tools list (no tool-use needed).
    assert provider.last_call["tools"] == []


@pytest.mark.asyncio
async def test_split_task_respects_max_subtasks():
    provider = _StubProvider(
        '{"split": true, "subtasks": ["1", "2", "3", "4", "5", "6", "7", "8"]}'
    )
    subs = await split_task(
        "task", provider=provider, model_id="m", max_subtasks=3,
    )
    assert subs == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_split_task_provider_failure_returns_empty():
    class _BoomProvider:
        async def complete_with_tools(self, **kw):
            raise RuntimeError("rate limited")
    subs = await split_task("anything", provider=_BoomProvider(), model_id="m")
    assert subs == []


@pytest.mark.asyncio
async def test_split_task_empty_text_returns_empty():
    """Don't even bother calling the provider on empty input."""
    class _NeverCalled:
        async def complete_with_tools(self, **kw):
            raise AssertionError("should not be called")
    assert await split_task("", provider=_NeverCalled(), model_id="m") == []
    assert await split_task("   ", provider=_NeverCalled(), model_id="m") == []
