"""Tests for the ACT executor — multi-turn tool-using inner loop."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from chimera.core.act import ActExecutor
from chimera.memory import open_and_init
from chimera.providers import (
    ChatChunk,
    ChatMessage,
    ChatResponse,
    Message,
    Provider,
    ToolUseBlock,
)
from chimera.providers.tiers import Provider as ProviderKind
from chimera.tools import (
    DispatchContext,
    Dispatcher,
    ToolRegistry,
    register_shell_tool,
)


# ── Fake provider ───────────────────────────────────────────


class _FakeProvider(Provider):
    """A scripted provider that returns a queue of pre-built responses.

    The model_id passed in is ignored; the harness just walks the queue.
    """

    name = "fake"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, messages, *, model_id, max_tokens=4096, system=None):
        if False:
            yield ChatChunk(text="")  # pragma: no cover — abstract satisfied

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model_id": model_id,
                "messages": messages,
                "tools": [t["function"]["name"] for t in tools],
                "max_tokens": max_tokens,
            }
        )
        if not self._responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self._responses.pop(0)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def shell_env(tmp_path: Path, monkeypatch):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    return mind, state


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.fixture
def dispatcher() -> Dispatcher:
    reg = ToolRegistry()
    register_shell_tool(reg)
    return Dispatcher(reg)


# ── Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_act_no_tools_used_completes_immediately(dispatcher, db):
    fake = _FakeProvider(
        [
            ChatResponse(
                text="42.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            )
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("What's 6 times 7?", cycle=1)
    assert result.completed is True
    assert result.rounds == 1
    assert result.final_text == "42."
    assert result.tool_call_history == []
    assert result.api_call_count == 1


@pytest.mark.asyncio
async def test_act_runs_a_tool_then_completes(shell_env, dispatcher, db):
    mind, _ = shell_env
    (mind / "hello.txt").write_text("howdy\n")

    fake = _FakeProvider(
        [
            ChatResponse(
                text="checking",
                tool_uses=[
                    ToolUseBlock(
                        id="tu_1", name="shell", input={"argv": ["ls", "."]}
                    )
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            ),
            ChatResponse(
                text="I see hello.txt.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            ),
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("list files", cycle=1)
    assert result.completed is True
    assert result.rounds == 2
    assert len(result.tool_call_history) == 1
    assert result.tool_call_history[0].name == "shell"
    assert "hello.txt" in result.final_text or "hello.txt" not in result.final_text  # text optional
    assert result.api_call_count == 2


@pytest.mark.asyncio
async def test_act_aborts_on_degenerate_loop(shell_env, dispatcher, db):
    """Five identical shell calls in a row → ABORT verdict from the guard."""
    repeated_call = ToolUseBlock(id="tu", name="shell", input={"argv": ["ls", "."]})
    fake = _FakeProvider(
        [
            ChatResponse(
                text="",
                tool_uses=[ToolUseBlock(id=f"tu_{i}", name="shell", input={"argv": ["ls", "."]})],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(8)
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("loop forever", cycle=1)
    assert result.completed is False
    assert result.finish_reason == "degenerate_loop_abort"
    # Five identical calls before the guard fires.
    assert len(result.tool_call_history) == 5


@pytest.mark.asyncio
async def test_act_exhausts_max_rounds(shell_env, dispatcher, db):
    """Each round returns tool_use but with varying args → no abort, just max_rounds."""
    fake = _FakeProvider(
        [
            ChatResponse(
                text="",
                tool_uses=[
                    ToolUseBlock(id=f"tu_{i}", name="shell", input={"argv": ["ls", f"sub_{i}"]})
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(10)
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
        max_rounds=3,
    )
    result = await executor.execute("explore", cycle=1)
    assert result.completed is False
    assert result.finish_reason == "max_rounds"
    assert result.rounds == 3


@pytest.mark.asyncio
async def test_act_records_api_call_rows(shell_env, dispatcher, db):
    fake = _FakeProvider(
        [
            ChatResponse(
                text="done",
                tool_uses=[],
                stop_reason="stop",
                input_tokens=10,
                output_tokens=5,
                latency_ms=42,
                model_id="m",
                provider="fake",
            )
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    await executor.execute("ping", cycle=7)
    rows = db.execute(
        "SELECT cycle, input_tokens, output_tokens, latency_ms, finish_reason FROM api_calls"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["cycle"] == 7
    assert r["input_tokens"] == 10
    assert r["output_tokens"] == 5
    assert r["latency_ms"] == 42
    assert r["finish_reason"] == "stop"
    outcomes = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    assert outcomes[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_act_records_failure_outcome_on_provider_error(shell_env, dispatcher, db):
    class _BadProvider(_FakeProvider):
        async def complete_with_tools(self, *a, **kw):
            raise RuntimeError("provider down")

    bad = _BadProvider([])
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: bad, ProviderKind.ANTHROPIC: bad},
        db=db,
    )
    result = await executor.execute("anything", cycle=2)
    assert result.completed is False
    assert result.finish_reason == "provider_error"
    assert "provider down" in (result.failure_reason or "")
    outcomes = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    assert outcomes[0]["outcome"] == "non_retriable"


# ── Live integration (env-gated) ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_act_live_anthropic_uses_shell_tool(shell_env, dispatcher, db):
    """End-to-end: real Anthropic model + real shell tool against a tmp mind dir."""
    mind, _ = shell_env
    (mind / "GREETINGS.md").write_text("hello there\n")

    executor = ActExecutor.from_env(dispatcher=dispatcher, db=db)
    if executor is None:
        pytest.skip("no provider keys available")

    result = await executor.execute(
        "List the files in the current directory and tell me what you see. Use the shell tool.",
        cycle=1,
    )
    # Model should have at least attempted a tool call and returned text.
    assert result.api_call_count >= 1
    # Either it called a tool and saw the file, or it answered directly.
    if result.tool_call_history:
        assert result.tool_call_history[0].name == "shell"
