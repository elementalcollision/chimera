"""Tests for v2.6 HTTP transport (server + client config)."""

from __future__ import annotations

import asyncio
import os

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from chimera.server.http_server import _BearerAuthMiddleware, build_http_app
from chimera.server.mcp_server import ChimeraMCPServer
from chimera.tools import MCPServerConfig, parse_mcp_config


# ── config parsing ──────────────────────────────────────────


def test_parse_mcp_config_stdio_default():
    raw = '{"alpha": {"command": "chimera", "args": ["serve"]}}'
    cfg = parse_mcp_config(raw)
    assert cfg["alpha"].transport == "stdio"
    assert cfg["alpha"].command == "chimera"
    assert cfg["alpha"].args == ("serve",)
    assert cfg["alpha"].url == ""


def test_parse_mcp_config_http_branch():
    raw = """{
      "remote": {
        "transport": "http",
        "url": "http://10.0.0.5:8765/mcp",
        "token": "secret"
      }
    }"""
    cfg = parse_mcp_config(raw)
    assert cfg["remote"].transport == "http"
    assert cfg["remote"].url == "http://10.0.0.5:8765/mcp"
    assert cfg["remote"].token == "secret"
    assert cfg["remote"].command == ""


def test_parse_mcp_config_http_without_url_skipped():
    raw = '{"bad": {"transport": "http"}}'
    cfg = parse_mcp_config(raw)
    assert "bad" not in cfg


def test_parse_mcp_config_unknown_transport_skipped():
    raw = '{"bad": {"transport": "carrier-pigeon", "url": "http://x"}}'
    cfg = parse_mcp_config(raw)
    assert "bad" not in cfg


def test_parse_mcp_config_stdio_without_command_skipped():
    raw = '{"bad": {"transport": "stdio"}}'
    cfg = parse_mcp_config(raw)
    assert "bad" not in cfg


def test_parse_mcp_config_mixed():
    raw = """{
      "local":  {"command": "chimera", "args": ["serve"]},
      "remote": {"transport": "http", "url": "http://10.0.0.5:8765/mcp"}
    }"""
    cfg = parse_mcp_config(raw)
    assert cfg["local"].transport == "stdio"
    assert cfg["remote"].transport == "http"


# ── ASGI app smoke tests ────────────────────────────────────


@pytest.fixture
def http_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    return build_http_app(cms)


def test_health_endpoint_no_auth_required(http_app, monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "secret-abc")
    # Note: middleware reads env at construction. Build a fresh app for this case.
    from chimera.server.http_server import build_http_app as _build
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    app = _build(cms)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "chimera ok" in resp.text


def test_healthz_returns_structured_status(http_app):
    with TestClient(http_app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "version" in body
        assert body["db"] == "ok"


def test_mcp_requires_bearer_when_token_set(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "secret-abc")
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    app = build_http_app(cms)
    with TestClient(app) as client:
        # No auth header → 401.
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert resp.status_code == 401
        # Wrong scheme → 401.
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Basic foo"},
        )
        assert resp.status_code == 401
        # Wrong token → 401.
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401


def test_mcp_anonymous_allowed_when_token_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CHIMERA_PEER_TOKEN", raising=False)
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    app = build_http_app(cms)
    # The middleware lets requests through (we don't bother sending a valid
    # MCP payload — just want to see we got past the auth gate).
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        # Without proper MCP session-id headers we won't get 200, but it must
        # not be 401 (auth bypassed).
        assert resp.status_code != 401


def test_bearer_middleware_logs_warning_when_constructed_with_empty_token(caplog):
    """Direct middleware instantiation logs the warning immediately."""
    with caplog.at_level("WARNING", logger="chimera.server.http_server"):
        _BearerAuthMiddleware(app=lambda *a: None, expected_token="")
    assert any("PEER_TOKEN" in r.message for r in caplog.records)
