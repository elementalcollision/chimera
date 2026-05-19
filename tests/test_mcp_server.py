"""Tests for Chimera's MCP server surface (v2.0)."""

from __future__ import annotations

import pytest

import mcp.types as mt

from chimera.server.mcp_server import (
    build_server,
    exposed_tool_names,
)
from chimera.tools import (
    Dispatcher,
    ToolRegistry,
    register_core_tools,
)


# ── exposed_tool_names env parsing ──────────────────────────


def test_exposed_tool_names_empty():
    assert exposed_tool_names("") == set()
    assert exposed_tool_names(None) == set() or exposed_tool_names(None) is not None


def test_exposed_tool_names_parses_csv():
    assert exposed_tool_names("shell, http_fetch ,code_exec") == {
        "shell",
        "http_fetch",
        "code_exec",
    }


def test_exposed_tool_names_ignores_empties():
    assert exposed_tool_names(",,shell,,,") == {"shell"}


# ── server wiring ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools_filters_to_exposed_set():
    """Only allow-listed tools appear on the wire."""
    reg = ToolRegistry()
    register_core_tools(reg)
    dispatcher = Dispatcher(reg)
    server = build_server(
        name="chimera-test",
        registry=reg,
        dispatcher=dispatcher,
        exposed=frozenset({"shell"}),
    )
    # Invoke the registered handler directly via the request handler map.
    handler = server.request_handlers[mt.ListToolsRequest]
    result = await handler(
        mt.ListToolsRequest(method="tools/list", params=None)
    )
    payload = result.root
    assert isinstance(payload, mt.ListToolsResult)
    names = {t.name for t in payload.tools}
    assert names == {"shell"}


@pytest.mark.asyncio
async def test_list_tools_empty_when_default_deny():
    reg = ToolRegistry()
    register_core_tools(reg)
    server = build_server(
        name="chimera-test",
        registry=reg,
        dispatcher=Dispatcher(reg),
        exposed=frozenset(),
    )
    handler = server.request_handlers[mt.ListToolsRequest]
    result = await handler(mt.ListToolsRequest(method="tools/list", params=None))
    assert result.root.tools == []


@pytest.mark.asyncio
async def test_call_tool_rejects_non_exposed(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path))
    reg = ToolRegistry()
    register_core_tools(reg)
    server = build_server(
        name="chimera-test",
        registry=reg,
        dispatcher=Dispatcher(reg),
        exposed=frozenset(),  # nothing exposed
    )
    handler = server.request_handlers[mt.CallToolRequest]
    req = mt.CallToolRequest(
        method="tools/call",
        params=mt.CallToolRequestParams(name="shell", arguments={"argv": ["ls"]}),
    )
    result = await handler(req)
    payload = result.root
    assert isinstance(payload, mt.CallToolResult)
    assert "not exposed" in payload.content[0].text


@pytest.mark.asyncio
async def test_call_tool_dispatches_when_exposed(monkeypatch, tmp_path):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    (mind / "marker.txt").write_text("hello")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    reg = ToolRegistry()
    register_core_tools(reg)
    server = build_server(
        name="chimera-test",
        registry=reg,
        dispatcher=Dispatcher(reg),
        exposed=frozenset({"shell"}),
    )
    handler = server.request_handlers[mt.CallToolRequest]
    req = mt.CallToolRequest(
        method="tools/call",
        params=mt.CallToolRequestParams(
            name="shell", arguments={"argv": ["ls", "."], "cwd": "mind"}
        ),
    )
    result = await handler(req)
    payload = result.root
    assert isinstance(payload, mt.CallToolResult)
    out = payload.content[0].text
    assert "marker.txt" in out
    assert "[exit=0]" in out
