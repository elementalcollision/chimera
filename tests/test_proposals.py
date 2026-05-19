"""Tests for proposal extraction + dedup + the Planner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chimera.core.strategy import Planner
from chimera.memory import open_and_init
from chimera.proposals import (
    MAX_PROPOSED_TASKS_PER_PLAN,
    ProposedTask,
    build_plan_prompt,
    cluster_key,
    dedup,
    extract_proposals,
    fingerprint,
)
from chimera.providers import ChatResponse, Message, Provider
from chimera.providers.tiers import Provider as ProviderKind


# ── extract_proposals ────────────────────────────────────────


def test_extract_proposals_parses_fenced_block():
    text = """Let me think.

```tasks
[
  {"text": "Append a lesson", "rationale": "we learned X"},
  {"text": "Read INBOX"}
]
```
"""
    out = extract_proposals(text)
    assert len(out) == 2
    assert out[0].text == "Append a lesson"
    assert out[0].rationale == "we learned X"
    assert out[1].text == "Read INBOX"
    assert out[1].rationale is None


def test_extract_proposals_caps_at_three():
    items = ", ".join(f'{{"text": "task {i}"}}' for i in range(10))
    text = f"```tasks\n[{items}]\n```"
    out = extract_proposals(text)
    assert len(out) == MAX_PROPOSED_TASKS_PER_PLAN == 3


def test_extract_proposals_returns_empty_for_no_fence():
    assert extract_proposals("Just prose, no tasks block.") == []


def test_extract_proposals_returns_empty_for_malformed_json():
    text = "```tasks\n[ not valid json\n```"
    assert extract_proposals(text) == []


def test_extract_proposals_skips_non_dict_items():
    text = '```tasks\n[{"text": "ok"}, "bad", 42, {"missing": "text"}]\n```'
    out = extract_proposals(text)
    assert len(out) == 1
    assert out[0].text == "ok"


# ── fingerprint + cluster_key ────────────────────────────────


def test_fingerprint_stable_for_word_reorder():
    a = fingerprint("Append the lesson to LESSONS.md")
    b = fingerprint("To LESSONS.md append the lesson")
    assert a == b


def test_fingerprint_differs_for_different_content():
    a = fingerprint("Append lesson")
    b = fingerprint("Delete lesson")
    assert a != b


def test_cluster_key_extracts_basename_and_verb():
    basename, verb = cluster_key("Append the lesson to mind/LESSONS.md")
    assert basename == "lessons.md"
    assert verb == "append"


def test_cluster_key_normalises_add_to_append():
    _, verb = cluster_key("Add a new line to TODO.md")
    assert verb == "append"


def test_cluster_key_no_basename_returns_none():
    basename, verb = cluster_key("List directory contents")
    assert basename is None
    assert verb == "list"


# ── dedup ────────────────────────────────────────────────────


def test_dedup_removes_self_duplicates_via_fingerprint():
    proposals = [
        ProposedTask(text="Append lesson to LESSONS.md"),
        ProposedTask(text="To LESSONS.md append a lesson"),  # same fingerprint
    ]
    survivors = dedup(proposals)
    assert len(survivors) == 1


def test_dedup_removes_self_duplicates_via_cluster_verb():
    proposals = [
        ProposedTask(text="Append the morning thought to JOURNAL.md"),
        ProposedTask(text="Add the evening reflection to JOURNAL.md"),
        # both map to (journal.md, append) under verb-normalisation
    ]
    survivors = dedup(proposals)
    assert len(survivors) == 1


def test_dedup_respects_existing_inbox():
    proposals = [
        ProposedTask(text="Append a note to LESSONS.md"),
        ProposedTask(text="Read INBOX.md"),
    ]
    survivors = dedup(proposals, existing_tasks=["Append a note to LESSONS.md"])
    assert len(survivors) == 1
    assert survivors[0].text == "Read INBOX.md"


def test_dedup_preserves_order():
    proposals = [
        ProposedTask(text="First task"),
        ProposedTask(text="Second task"),
        ProposedTask(text="Third task"),
    ]
    survivors = dedup(proposals)
    assert [p.text for p in survivors] == ["First task", "Second task", "Third task"]


# ── plan-prompt rendering ────────────────────────────────────


def test_build_plan_prompt_includes_open_tasks_and_summary():
    prompt = build_plan_prompt(
        cycle=8,
        open_tasks=["Read X", "Edit Y"],
        recent_summary="(no prior activity)",
    )
    assert "Cycle: 8" in prompt or "cycle: 8" in prompt.lower()
    assert "Read X" in prompt
    assert "Edit Y" in prompt


def test_build_plan_prompt_handles_no_open_tasks():
    prompt = build_plan_prompt(cycle=4, open_tasks=[], recent_summary="")
    assert "(none)" in prompt


# ── Planner with a fake provider ─────────────────────────────


class _ScriptedPlanProvider(Provider):
    name = "scripted"

    def __init__(self, response: ChatResponse) -> None:
        self._response = response

    async def stream(self, *a, **kw):  # pragma: no cover
        if False:
            yield None

    async def complete_with_tools(self, *a, **kw) -> ChatResponse:
        return self._response


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.mark.asyncio
async def test_planner_skips_off_cycle(db):
    prov = _ScriptedPlanProvider(
        ChatResponse(text="", tool_uses=[], stop_reason="stop", model_id="m", provider="s")
    )
    p = Planner(
        providers={ProviderKind.OPENROUTER: prov, ProviderKind.ANTHROPIC: prov}, db=db
    )
    result = await p.maybe_plan(cycle=3, every_n=4, open_tasks=[])
    assert result.skipped is True
    assert result.proposals == []


@pytest.mark.asyncio
async def test_planner_extracts_and_dedups(db):
    prov = _ScriptedPlanProvider(
        ChatResponse(
            text=(
                "```tasks\n"
                '[{"text": "Append idea to LESSONS.md", "rationale": "novel angle"},'
                ' {"text": "Add lesson to LESSONS.md"}]\n'  # dup with first via verb
                "```"
            ),
            tool_uses=[],
            stop_reason="stop",
            model_id="opus",
            provider="scripted",
        )
    )
    p = Planner(
        providers={ProviderKind.OPENROUTER: prov, ProviderKind.ANTHROPIC: prov}, db=db
    )
    result = await p.maybe_plan(cycle=4, every_n=4, open_tasks=[])
    assert result.skipped is False
    assert len(result.proposals) == 1
    assert result.proposals[0].text == "Append idea to LESSONS.md"
    assert result.api_call_count == 1
    # Recorded in DB.
    rows = db.execute("SELECT cycle, finish_reason FROM api_calls").fetchall()
    assert len(rows) == 1
    assert rows[0]["cycle"] == 4
    outcome_rows = db.execute("SELECT outcome, task_type FROM ladder_outcomes").fetchall()
    assert outcome_rows[0]["task_type"] == "plan"
    assert outcome_rows[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_planner_records_failure_on_provider_error(db):
    class _BadProvider(_ScriptedPlanProvider):
        async def complete_with_tools(self, *a, **kw):
            raise RuntimeError("opus is asleep")

    bad = _BadProvider(
        ChatResponse(text="", tool_uses=[], stop_reason="stop", model_id="m", provider="s")
    )
    p = Planner(
        providers={ProviderKind.OPENROUTER: bad, ProviderKind.ANTHROPIC: bad}, db=db
    )
    result = await p.maybe_plan(cycle=4, every_n=4, open_tasks=[])
    assert result.skipped is False
    assert result.failure_reason == "opus is asleep"
    rows = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    assert rows[0]["outcome"] == "non_retriable"


@pytest.mark.asyncio
async def test_planner_drops_existing_inbox_duplicates(db):
    prov = _ScriptedPlanProvider(
        ChatResponse(
            text=(
                "```tasks\n"
                '[{"text": "Read INBOX.md"}, {"text": "Compute SHA"}]\n'
                "```"
            ),
            tool_uses=[],
            stop_reason="stop",
            model_id="opus",
            provider="scripted",
        )
    )
    p = Planner(
        providers={ProviderKind.OPENROUTER: prov, ProviderKind.ANTHROPIC: prov}, db=db
    )
    result = await p.maybe_plan(
        cycle=4, every_n=4, open_tasks=["Read INBOX.md"]
    )
    assert len(result.proposals) == 1
    assert result.proposals[0].text == "Compute SHA"
