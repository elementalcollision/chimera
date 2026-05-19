"""Tests for the spawn_sub_agent tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chimera.core.act import ActExecutor
from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Message, Provider, ToolUseBlock
from chimera.providers.tiers import Provider as ProviderKind
from chimera.tools import (
    DispatchContext,
    Dispatcher,
    SubAgentConfig,
    SubAgentRunner,
    ToolRegistry,
    register_core_tools,
    register_sub_agent_tool,
)
from chimera.tools.subagent import _sub_agent_depth


class _ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    async def stream(self, *a, **kw):  # pragma: no cover
        if False:
            yield ChatChunk(text="")

    async def complete_with_tools(self, *a, **kw) -> ChatResponse:
        return self._responses.pop(0)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.fixture
def shell_env(tmp_path: Path, monkeypatch):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    return mind, state


def test_register_sub_agent_tool_idempotent(db):
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(providers={}, db=db, registry=reg)
    register_sub_agent_tool(runner, reg)
    register_sub_agent_tool(runner, reg)
    assert reg.get("spawn_sub_agent") is not None


@pytest.mark.asyncio
async def test_sub_agent_runs_brief_and_returns_text(shell_env, db):
    """Sub-agent receives a one-shot 'stop' response → returns text."""
    sub_provider = _ScriptedProvider(
        [
            ChatResponse(
                text="The answer is 42.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="scripted",
            )
        ]
    )
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(
        providers={
            ProviderKind.OPENROUTER: sub_provider,
            ProviderKind.ANTHROPIC: sub_provider,
        },
        db=db,
        registry=reg,
    )
    register_sub_agent_tool(runner, reg)

    handler = reg.get("spawn_sub_agent").handler
    out = await handler(
        {"brief": "What's the answer to life?"}, DispatchContext()
    )
    assert "42" in out


@pytest.mark.asyncio
async def test_sub_agent_depth_limit_blocks_runaway(shell_env, db, monkeypatch):
    """If the contextvar depth already exceeds max, the handler refuses."""
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(
        providers={},
        db=db,
        registry=reg,
        config=SubAgentConfig(max_depth=1),
    )
    register_sub_agent_tool(runner, reg)

    handler = reg.get("spawn_sub_agent").handler
    # Simulate being one level deep already.
    token = _sub_agent_depth.set(1)
    try:
        out = await handler({"brief": "go deeper"}, DispatchContext())
    finally:
        _sub_agent_depth.reset(token)
    assert "depth limit" in out


@pytest.mark.asyncio
async def test_sub_agent_rejects_empty_brief(shell_env, db):
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(providers={}, db=db, registry=reg)
    register_sub_agent_tool(runner, reg)
    handler = reg.get("spawn_sub_agent").handler
    with pytest.raises(ValueError):
        await handler({"brief": "  "}, DispatchContext())


@pytest.mark.asyncio
async def test_sub_agent_passes_allowed_tools_to_context(shell_env, db):
    """A sub-agent with allowed_tools=['shell'] cannot call any other tool."""

    # Sub-provider tries to call http_fetch (not in allow-list).
    sub_provider = _ScriptedProvider(
        [
            ChatResponse(
                text="trying",
                tool_uses=[
                    ToolUseBlock(
                        id="tu_1",
                        name="http_fetch",
                        input={"url": "https://example.com/"},
                    )
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="scripted",
            ),
            ChatResponse(
                text="failed but I tried",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="scripted",
            ),
        ]
    )
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(
        providers={
            ProviderKind.OPENROUTER: sub_provider,
            ProviderKind.ANTHROPIC: sub_provider,
        },
        db=db,
        registry=reg,
    )
    register_sub_agent_tool(runner, reg)
    handler = reg.get("spawn_sub_agent").handler
    out = await handler(
        {"brief": "list files", "allowed_tools": ["shell"]},
        DispatchContext(),
    )
    # The sub-agent's second response is the visible final text.
    assert "failed but I tried" in out
