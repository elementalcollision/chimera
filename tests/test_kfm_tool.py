"""Tests for the v2.3 chimera-kfm-state tool + fetch_peer_kfm."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import mcp.types as mt

from chimera.a2a import fetch_peer_kfm
from chimera.core.mind import HeartbeatState, save_heartbeat
from chimera.memory import create_entity, open_and_init
from chimera.server import (
    IDENTITY_TOOL_NAME,
    KFM_STATE_TOOL_NAME,
    register_kfm_state_tool,
)
from chimera.server.mcp_server import ChimeraMCPServer
from chimera.tools import DispatchContext, ToolRegistry
from chimera.trust import TrustManager


@pytest.fixture
def chimera_env(tmp_path: Path, monkeypatch) -> Path:
    """Spin up a fake Chimera state for the kfm-state tool to read."""
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    save_heartbeat(
        mind / "HEARTBEAT.md",
        HeartbeatState(cycle=12, trust_tier="T2", last_drift_score=0.18),
        "",
    )
    tm = TrustManager(state / "trust_state.json", min_dwell_seconds=0)
    tm.promote()  # T1
    tm.promote()  # T2
    conn = open_and_init(state / "chimera.db")
    create_entity(conn, kind="plan", name="current", cycle=5, initial_state="STABLE")
    conn.close()
    return tmp_path


def test_register_kfm_state_tool_idempotent():
    reg = ToolRegistry()
    register_kfm_state_tool(reg)
    register_kfm_state_tool(reg)
    assert reg.get(KFM_STATE_TOOL_NAME) is not None


@pytest.mark.asyncio
async def test_kfm_state_tool_returns_snapshot(chimera_env):
    reg = ToolRegistry()
    register_kfm_state_tool(reg)
    handler = reg.get(KFM_STATE_TOOL_NAME).handler
    payload = json.loads(await handler({}, DispatchContext()))
    assert payload["cycle"] == 12
    assert payload["plan_kfm_state"] == "STABLE"
    assert payload["plan_name"] == "current"
    assert payload["trust_tier"] in {"T2", "UNLOCKED"}
    assert payload["trust_tier_int"] == 2
    assert payload["last_drift_score"] == 0.18


@pytest.mark.asyncio
async def test_kfm_state_tool_handles_missing_state(tmp_path, monkeypatch):
    """No HEARTBEAT, no DB, no trust state — handler still returns valid JSON."""
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "missing_mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "missing_state"))
    reg = ToolRegistry()
    register_kfm_state_tool(reg)
    handler = reg.get(KFM_STATE_TOOL_NAME).handler
    payload = json.loads(await handler({}, DispatchContext()))
    assert payload["cycle"] == 0
    assert payload["plan_kfm_state"] is None
    assert payload["trust_tier_int"] == 0


@pytest.mark.asyncio
async def test_kfm_state_in_always_exposed_set(monkeypatch, chimera_env):
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env()
    assert KFM_STATE_TOOL_NAME in cms.exposed
    assert IDENTITY_TOOL_NAME in cms.exposed


@pytest.mark.asyncio
async def test_kfm_state_advertised_by_list_tools(monkeypatch, chimera_env):
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env()
    handler = cms.server.request_handlers[mt.ListToolsRequest]
    result = await handler(mt.ListToolsRequest(method="tools/list", params=None))
    names = {t.name for t in result.root.tools}
    assert KFM_STATE_TOOL_NAME in names


@pytest.mark.asyncio
async def test_fetch_peer_kfm_parses_payload():
    reg = ToolRegistry()

    async def _handler(args, ctx):
        return json.dumps({
            "cycle": 7,
            "trust_tier": "T3",
            "trust_tier_int": 3,
            "plan_kfm_state": "STABLE",
            "plan_name": "current",
            "last_drift_score": 0.05,
        })

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
        handler=_handler,
    )
    out = await fetch_peer_kfm("alpha", registry=reg)
    assert out["cycle"] == 7
    assert out["plan_kfm_state"] == "STABLE"


@pytest.mark.asyncio
async def test_fetch_peer_kfm_raises_for_unknown_peer():
    reg = ToolRegistry()
    with pytest.raises(LookupError):
        await fetch_peer_kfm("nobody", registry=reg)
