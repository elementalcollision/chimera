"""Tests for v2.5 PeerAwareDispatcher."""

from __future__ import annotations

import json

import pytest

from chimera.a2a import (
    PeerAwareDispatcher,
    PeerCallRefused,
    PeerStateCache,
    PeerTrustPolicy,
)
from chimera.tools import DispatchContext, ToolRegistry


# ── helpers ─────────────────────────────────────────────────


def _register_peer_kfm_tool(reg: ToolRegistry, peer: str, state: dict | None) -> None:
    """Register a fake mcp-<peer>-chimera-kfm-state tool that returns the given state."""

    async def _handler(args, ctx):
        if state is None:
            raise RuntimeError("peer offline")
        return json.dumps(state)

    reg.register(
        name=f"mcp-{peer}-chimera-kfm-state",
        toolset=f"mcp-{peer}",
        schema={
            "type": "function",
            "function": {
                "name": f"mcp-{peer}-chimera-kfm-state",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handler,
    )


def _register_peer_data_tool(reg: ToolRegistry, peer: str, payload: str) -> list[DispatchContext]:
    """Register mcp-<peer>-shell; returns the list capturing dispatched contexts."""
    captured: list[DispatchContext] = []

    async def _handler(args, ctx):
        captured.append(ctx)
        return payload

    reg.register(
        name=f"mcp-{peer}-shell",
        toolset=f"mcp-{peer}",
        schema={
            "type": "function",
            "function": {
                "name": f"mcp-{peer}-shell",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handler,
    )
    return captured


# ── allow path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_healthy_peer_passes_through_with_caller_context():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg,
        "alpha",
        {"plan_kfm_state": "STABLE", "trust_tier_int": 3, "last_drift_score": 0.05},
    )
    captured = _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg)
    out = await pad.dispatch(
        "mcp-alpha-shell",
        {"argv": ["ls"]},
        DispatchContext(trust_tier="T3", session_id="sid"),
    )
    assert out == "ok"
    assert len(captured) == 1
    assert captured[0].trust_tier == "T3"
    assert captured[0].session_id == "sid"


# ── refuse paths ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refuse_when_peer_plan_deprecated():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg, "alpha", {"plan_kfm_state": "DEPRECATED", "trust_tier_int": 3}
    )
    _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg)
    with pytest.raises(PeerCallRefused, match="DEPRECATED"):
        await pad.dispatch("mcp-alpha-shell", {}, DispatchContext())


@pytest.mark.asyncio
async def test_refuse_when_peer_drift_above_lockdown():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg,
        "alpha",
        {"plan_kfm_state": "STABLE", "trust_tier_int": 3, "last_drift_score": 0.5},
    )
    _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg)
    with pytest.raises(PeerCallRefused, match="drift"):
        await pad.dispatch("mcp-alpha-shell", {}, DispatchContext())


# ── degrade path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_degrade_downgrades_context_to_t1():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg, "alpha", {"plan_kfm_state": "EXPERIMENTAL", "trust_tier_int": 3}
    )
    captured = _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg)
    await pad.dispatch(
        "mcp-alpha-shell",
        {},
        DispatchContext(trust_tier="T3", session_id="root"),
    )
    assert captured[0].trust_tier == "T1"
    # session_id preserved.
    assert captured[0].session_id == "root"


@pytest.mark.asyncio
async def test_degrade_when_peer_state_unavailable():
    reg = ToolRegistry()
    _register_peer_kfm_tool(reg, "alpha", None)  # handler raises
    captured = _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg)
    await pad.dispatch(
        "mcp-alpha-shell", {}, DispatchContext(trust_tier="T3")
    )
    assert captured[0].trust_tier == "T1"


# ── always-allowed paths ────────────────────────────────────


@pytest.mark.asyncio
async def test_identity_tool_bypasses_policy_even_when_peer_refused():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg, "alpha", {"plan_kfm_state": "KILLED", "trust_tier_int": 0}
    )

    async def _identity_handler(args, ctx):
        return json.dumps({"agent_id": "chimera-alpha", "role": "chimera"})

    reg.register(
        name="mcp-alpha-chimera-identity",
        toolset="mcp-alpha",
        schema={
            "type": "function",
            "function": {
                "name": "mcp-alpha-chimera-identity",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_identity_handler,
    )
    pad = PeerAwareDispatcher(reg)
    out = await pad.dispatch("mcp-alpha-chimera-identity", {}, DispatchContext())
    assert "chimera-alpha" in out


# ── caching ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_peer_state_fetched_once_within_ttl():
    """Two consecutive calls to mcp-alpha-shell should only fetch state once."""
    reg = ToolRegistry()
    fetch_count = {"n": 0}

    async def _kfm_handler(args, ctx):
        fetch_count["n"] += 1
        return json.dumps({"plan_kfm_state": "STABLE", "trust_tier_int": 3})

    reg.register(
        name="mcp-alpha-chimera-kfm-state",
        toolset="mcp-alpha",
        schema={
            "type": "function",
            "function": {
                "name": "mcp-alpha-chimera-kfm-state",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_kfm_handler,
    )
    _register_peer_data_tool(reg, "alpha", "ok")
    pad = PeerAwareDispatcher(reg, cache=PeerStateCache(ttl_seconds=60))
    await pad.dispatch("mcp-alpha-shell", {}, DispatchContext())
    await pad.dispatch("mcp-alpha-shell", {}, DispatchContext())
    assert fetch_count["n"] == 1


# ── non-peer tools pass through ─────────────────────────────


@pytest.mark.asyncio
async def test_non_mcp_tool_is_unaffected():
    reg = ToolRegistry()
    captured = []

    async def _handler(args, ctx):
        captured.append(ctx)
        return "local-ok"

    reg.register(
        name="local_tool",
        toolset="core",
        schema={
            "type": "function",
            "function": {
                "name": "local_tool",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        handler=_handler,
    )
    pad = PeerAwareDispatcher(reg)
    out = await pad.dispatch(
        "local_tool", {}, DispatchContext(trust_tier="T5")
    )
    assert out == "local-ok"
    assert captured[0].trust_tier == "T5"


# ── custom policy ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_strict_policy_refuses_otherwise_allowed_peer():
    reg = ToolRegistry()
    _register_peer_kfm_tool(
        reg, "alpha", {"plan_kfm_state": "STABLE", "trust_tier_int": 3}
    )
    _register_peer_data_tool(reg, "alpha", "ok")
    strict = PeerTrustPolicy(min_trust_tier_for_allow=5)
    pad = PeerAwareDispatcher(reg, policy=strict)
    # T3 is below the strict min (T5) → degrade, not refuse.
    captured = []

    async def _capture(args, ctx):
        captured.append(ctx)
        return "ok"

    # Rebind the data tool to capture context.
    reg.register(
        name="mcp-alpha-shell",
        toolset="mcp-alpha",
        schema={"type": "function", "function": {"name": "mcp-alpha-shell", "description": "", "parameters": {}}},
        handler=_capture,
        override=True,
    )
    await pad.dispatch("mcp-alpha-shell", {}, DispatchContext(trust_tier="T5"))
    assert captured[0].trust_tier == "T1"
