"""Tests for the MCP client config parsing + registration plumbing."""

from __future__ import annotations

import pytest

from chimera.tools import MCPServerConfig, ToolRegistry, parse_mcp_config
from chimera.tools.mcp_client import register_mcp_servers_from_env


# ── config parsing ──────────────────────────────────────────


def test_parse_mcp_config_empty():
    assert parse_mcp_config(None) == {}
    assert parse_mcp_config("") == {}


def test_parse_mcp_config_simple():
    raw = '{"fs": {"command": "npx", "args": ["-y", "server-fs", "/mind"]}}'
    cfg = parse_mcp_config(raw)
    assert "fs" in cfg
    assert cfg["fs"].command == "npx"
    assert cfg["fs"].args == ("-y", "server-fs", "/mind")
    assert cfg["fs"].env == {}


def test_parse_mcp_config_with_env():
    raw = '{"gh": {"command": "gh-mcp", "env": {"GITHUB_TOKEN": "xxx"}}}'
    cfg = parse_mcp_config(raw)
    assert cfg["gh"].env == {"GITHUB_TOKEN": "xxx"}


def test_parse_mcp_config_malformed_json_returns_empty(caplog):
    assert parse_mcp_config("{not json") == {}


def test_parse_mcp_config_non_object_returns_empty():
    assert parse_mcp_config('"just a string"') == {}
    assert parse_mcp_config("[1, 2, 3]") == {}


def test_parse_mcp_config_missing_command_skipped():
    raw = '{"x": {"args": ["a"]}, "y": {"command": "ok"}}'
    cfg = parse_mcp_config(raw)
    assert "x" not in cfg
    assert "y" in cfg


# ── registration handles failures gracefully ────────────────


@pytest.mark.asyncio
async def test_register_mcp_servers_from_env_with_no_config_returns_empty(monkeypatch):
    monkeypatch.delenv("CHIMERA_MCP_SERVERS", raising=False)
    reg = ToolRegistry()
    counts = await register_mcp_servers_from_env(reg)
    assert counts == {}
    assert reg.names() == []


@pytest.mark.asyncio
async def test_register_mcp_servers_handles_unreachable_command(monkeypatch):
    """Bogus command must not crash the loop; just log and yield 0 tools."""
    monkeypatch.setenv(
        "CHIMERA_MCP_SERVERS",
        '{"bogus": {"command": "this-command-absolutely-does-not-exist-zxy"}}',
    )
    reg = ToolRegistry()
    counts = await register_mcp_servers_from_env(reg)
    assert counts == {"bogus": 0}
    assert reg.names() == []
