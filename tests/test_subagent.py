"""Tests for the spawn_sub_agent tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Provider, ToolUseBlock
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


@pytest.fixture(autouse=True)
def _isolate_v4115_v4118_from_git_state(monkeypatch):
    """Isolate test_subagent from v4.115/v4.118 git-reading detectors per ADR 0122.

    See tests/test_act.py for the rationale: the ACT pipeline shells out to
    `git log` / `git diff` via check_commit_message_diff_drift (v4.115) and
    check_provenance_claim_valid (v4.118), which can read the real branch
    HEAD and trip during sub-agent tests.
    """
    from chimera.core import act as _act

    monkeypatch.setattr(
        _act, "check_commit_message_diff_drift", lambda *a, **kw: []
    )
    monkeypatch.setattr(
        _act, "check_provenance_claim_valid", lambda *a, **kw: []
    )


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


# ── v4.49: sub-agent failure visibility ─────────────────────


@pytest.mark.asyncio
async def test_sub_agent_failure_raises_structured_error(shell_env, db):
    """When the sub-agent's ActResult.completed is False, the runner
    raises SubAgentFailed with finish_reason + failure_reason so the
    parent model sees an actionable is_error tool_result."""
    from chimera.tools.subagent import SubAgentFailed

    # Script a provider that exhausts rounds — never returns stop.
    fake = _ScriptedProvider(
        [
            ChatResponse(
                text="thinking",
                tool_uses=[ToolUseBlock(id=f"tu_{i}", name="shell",
                                        input={"argv": ["ls", "."]})],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(20)
        ]
    )
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(
        providers={
            ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake,
        },
        db=db,
        registry=reg,
    )

    with pytest.raises(SubAgentFailed) as exc_info:
        await runner.run("compute fibonacci", tier="haiku")
    err = exc_info.value
    assert err.finish_reason == "max_rounds"
    assert err.tier == "haiku"
    assert err.rounds_used >= 1
    msg = str(err)
    assert "sub-agent FAILED" in msg
    assert "tier='haiku'" in msg
    assert "finish_reason=max_rounds" in msg


@pytest.mark.asyncio
async def test_sub_agent_failure_propagates_through_dispatcher(shell_env, db):
    """End-to-end: spawn_sub_agent handler raises SubAgentFailed; the
    dispatcher re-raises so ACT's _run_one wraps it as is_error=True."""

    fake = _ScriptedProvider(
        [
            ChatResponse(
                text="loop",
                tool_uses=[ToolUseBlock(id=f"tu_{i}", name="shell",
                                        input={"argv": ["ls", "."]})],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(20)
        ]
    )
    reg = ToolRegistry()
    register_core_tools(reg)
    runner = SubAgentRunner(
        providers={
            ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake,
        },
        db=db,
        registry=reg,
    )
    register_sub_agent_tool(runner, reg)

    disp = Dispatcher(reg)
    with pytest.raises(Exception) as exc_info:
        await disp.dispatch(
            "spawn_sub_agent",
            {"brief": "loop forever doing nothing"},
            DispatchContext(),
        )
    assert "sub-agent FAILED" in str(exc_info.value)
