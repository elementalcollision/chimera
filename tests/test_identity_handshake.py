"""Tests for v2.1 peer identity handshake."""

from __future__ import annotations

import json

import pytest
import mcp.types as mt

from chimera.a2a import AgentIdentity, fetch_peer_identity, list_peer_chimeras
from chimera.server import IDENTITY_TOOL_NAME, register_identity_tool
from chimera.server.mcp_server import ChimeraMCPServer, build_server
from chimera.tools import Dispatcher, DispatchContext, ToolRegistry


# ── server side ─────────────────────────────────────────────


def test_register_identity_tool_idempotent():
    reg = ToolRegistry()
    register_identity_tool(reg)
    register_identity_tool(reg)
    assert reg.get(IDENTITY_TOOL_NAME) is not None


@pytest.mark.asyncio
async def test_identity_tool_returns_agent_identity_payload():
    reg = ToolRegistry()
    register_identity_tool(reg)
    handler = reg.get(IDENTITY_TOOL_NAME).handler
    out = await handler({}, DispatchContext())
    data = json.loads(out)
    assert data["role"] == "chimera"
    assert data["agent_id"].startswith("chimera-")
    assert "shell" in data["capabilities"]


@pytest.mark.asyncio
async def test_identity_tool_always_in_exposed_set_via_from_env(monkeypatch):
    """Even with an empty allow-list, ChimeraMCPServer.from_env exposes identity."""
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env()
    assert IDENTITY_TOOL_NAME in cms.exposed


@pytest.mark.asyncio
async def test_list_tools_includes_identity_even_when_allowlist_empty(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env()
    handler = cms.server.request_handlers[mt.ListToolsRequest]
    result = await handler(mt.ListToolsRequest(method="tools/list", params=None))
    names = {t.name for t in result.root.tools}
    assert IDENTITY_TOOL_NAME in names


# ── client side ─────────────────────────────────────────────


def test_list_peer_chimeras_finds_handshake_tools():
    reg = ToolRegistry()

    async def _noop(args, ctx):
        return "{}"

    schema = {
        "type": "function",
        "function": {"name": "mcp-alpha-chimera-identity", "description": "", "parameters": {"type": "object", "properties": {}}},
    }
    reg.register(
        name="mcp-alpha-chimera-identity",
        toolset="mcp-alpha",
        schema=schema,
        handler=_noop,
    )
    schema2 = dict(schema)
    schema2["function"] = {**schema["function"], "name": "mcp-alpha-shell"}
    reg.register(
        name="mcp-alpha-shell",
        toolset="mcp-alpha",
        schema=schema2,
        handler=_noop,
    )
    schema3 = dict(schema)
    schema3["function"] = {**schema["function"], "name": "mcp-beta-chimera-identity"}
    reg.register(
        name="mcp-beta-chimera-identity",
        toolset="mcp-beta",
        schema=schema3,
        handler=_noop,
    )
    assert list_peer_chimeras(reg) == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_fetch_peer_identity_parses_payload():
    reg = ToolRegistry()

    identity = AgentIdentity(agent_id="chimera-test-peer")

    async def _handler(args, ctx):
        return json.dumps(identity.to_dict())

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
        handler=_handler,
    )
    out = await fetch_peer_identity("alpha", registry=reg)
    assert out["agent_id"] == "chimera-test-peer"
    assert out["role"] == "chimera"


@pytest.mark.asyncio
async def test_fetch_peer_identity_raises_for_unknown_peer():
    reg = ToolRegistry()
    with pytest.raises(LookupError):
        await fetch_peer_identity("nope", registry=reg)
