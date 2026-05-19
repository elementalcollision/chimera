"""Tests for the web tools (http_fetch + web_search)."""

from __future__ import annotations

import os

import pytest

from chimera.tools import DispatchContext, ToolRegistry, register_web_tools
from chimera.tools.web import (
    HTTP_FETCH_SCHEMA,
    WEB_SEARCH_SCHEMA,
    http_fetch_handler,
    web_search_available,
    web_search_handler,
)


# ── schemas + registration ───────────────────────────────────


def test_schemas_are_openai_shaped():
    assert HTTP_FETCH_SCHEMA["type"] == "function"
    assert HTTP_FETCH_SCHEMA["function"]["name"] == "http_fetch"
    assert WEB_SEARCH_SCHEMA["function"]["name"] == "web_search"


def test_register_web_tools_is_idempotent():
    reg = ToolRegistry()
    register_web_tools(reg)
    register_web_tools(reg)  # second call must not raise
    assert reg.get("http_fetch") is not None
    assert reg.get("web_search") is not None


def test_web_search_check_fn_gates_on_keys(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    reg = ToolRegistry()
    register_web_tools(reg)
    assert reg.is_available("web_search") is False
    assert reg.is_available("http_fetch") is True  # no gate

    monkeypatch.setenv("EXA_API_KEY", "fake-key")
    # Fresh registry to avoid stale TTL cache.
    reg2 = ToolRegistry()
    register_web_tools(reg2)
    assert reg2.is_available("web_search") is True

    # Brave alone is enough too.
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "fake-brave")
    reg3 = ToolRegistry()
    register_web_tools(reg3)
    assert reg3.is_available("web_search") is True


# ── http_fetch validation ────────────────────────────────────


@pytest.mark.asyncio
async def test_http_fetch_rejects_empty_url():
    with pytest.raises(ValueError):
        await http_fetch_handler({}, DispatchContext())


@pytest.mark.asyncio
async def test_http_fetch_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        await http_fetch_handler({"url": "file:///etc/passwd"}, DispatchContext())


@pytest.mark.asyncio
async def test_http_fetch_rejects_localhost():
    with pytest.raises(PermissionError, match="private address"):
        await http_fetch_handler(
            {"url": "http://localhost:8000/secret"}, DispatchContext()
        )


@pytest.mark.asyncio
async def test_http_fetch_rejects_rfc1918():
    with pytest.raises(PermissionError, match="private address"):
        await http_fetch_handler(
            {"url": "http://192.168.1.1/admin"}, DispatchContext()
        )


# ── web_search without keys ──────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_raises_when_no_keys(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no backend configured"):
        await web_search_handler({"query": "test"}, DispatchContext())


@pytest.mark.asyncio
async def test_web_search_rejects_empty_query():
    with pytest.raises(ValueError):
        await web_search_handler({"query": "  "}, DispatchContext())


# ── live tests (env-gated) ───────────────────────────────────


@pytest.mark.asyncio
async def test_http_fetch_live_example_com():
    """Public-internet smoke test — example.com is the canonical safe target."""
    out = await http_fetch_handler(
        {"url": "https://example.com/", "max_chars": 500}, DispatchContext()
    )
    assert "GET https://example.com/" in out
    assert "status=200" in out
    assert "Example Domain" in out


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("EXA_API_KEY"),
    reason="EXA_API_KEY not set",
)
async def test_web_search_live_exa(monkeypatch):
    # Force Exa specifically (in case Brave or Tavily would otherwise win).
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = await web_search_handler(
        {"query": "Anthropic Claude documentation", "num_results": 3},
        DispatchContext(),
    )
    assert "Exa" in out
    assert "Anthropic" in out or "claude" in out.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("BRAVE_SEARCH_API_KEY"),
    reason="BRAVE_SEARCH_API_KEY not set",
)
async def test_web_search_live_brave(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = await web_search_handler(
        {"query": "Model Context Protocol Anthropic", "num_results": 3},
        DispatchContext(),
    )
    assert "Brave" in out
    assert "anthropic" in out.lower() or "mcp" in out.lower() or "context" in out.lower()
