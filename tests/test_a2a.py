"""Tests for the A2A spike (identity + peer helper)."""

from __future__ import annotations

from chimera import __version__
from chimera.a2a import AgentIdentity, list_xenocomm_tools
from chimera.tools import ToolRegistry


def test_agent_identity_defaults_carry_version():
    ident = AgentIdentity()
    assert ident.version == __version__
    assert ident.role == "chimera"
    assert "shell" in ident.capabilities
    assert ident.agent_id.startswith("chimera-")


def test_agent_identity_honours_env_override(monkeypatch):
    monkeypatch.setenv("CHIMERA_AGENT_ID", "chimera-alpha")
    ident = AgentIdentity()
    assert ident.agent_id == "chimera-alpha"


def test_list_xenocomm_tools_empty_when_none_registered():
    reg = ToolRegistry()
    assert list_xenocomm_tools(reg) == []


def test_list_xenocomm_tools_filters_by_toolset():
    reg = ToolRegistry()

    async def _noop(args, ctx):
        return "ok"

    reg.register(
        name="mcp-xenocomm-alignment",
        toolset="mcp-xenocomm",
        schema={"type": "function", "function": {"name": "mcp-xenocomm-alignment", "description": "", "parameters": {}}},
        handler=_noop,
    )
    reg.register(
        name="mcp-other-thing",
        toolset="mcp-other",
        schema={"type": "function", "function": {"name": "mcp-other-thing", "description": "", "parameters": {}}},
        handler=_noop,
    )
    found = list_xenocomm_tools(reg)
    assert found == ["mcp-xenocomm-alignment"]
