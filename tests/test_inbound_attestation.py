"""Tests for v2.7 inbound peer attestation."""

from __future__ import annotations

from pathlib import Path

import pytest
import mcp.types as mt
from starlette.testclient import TestClient

from chimera.a2a import AgentIdentity, register as register_peer
from chimera.server import current_peer, load_token_map, resolve_peer_for_token
from chimera.server.http_server import build_http_app
from chimera.server.mcp_server import ChimeraMCPServer
from chimera.server.peer_auth import lookup_peer_state


# ── token map parsing ──────────────────────────────────────


def test_load_token_map_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("CHIMERA_PEER_TOKENS", raising=False)
    assert load_token_map() == {}


def test_load_token_map_parses_json():
    raw = '{"abc": "chimera-alpha", "def": "chimera-beta"}'
    assert load_token_map(raw) == {"abc": "chimera-alpha", "def": "chimera-beta"}


def test_load_token_map_skips_non_string_pairs():
    raw = '{"abc": "ok", "123": null, "x": ""}'
    assert load_token_map(raw) == {"abc": "ok"}


def test_load_token_map_malformed_returns_empty():
    assert load_token_map("not json") == {}


def test_resolve_peer_for_token():
    tm = {"abc": "chimera-alpha"}
    assert resolve_peer_for_token("abc", token_map=tm) == "chimera-alpha"
    assert resolve_peer_for_token("nope", token_map=tm) is None


# ── lookup_peer_state via registry ─────────────────────────


@pytest.fixture
def reg_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "peers"
    d.mkdir()
    monkeypatch.setenv("CHIMERA_PEER_REGISTRY_DIR", str(d))
    return d


def test_lookup_peer_state_returns_state_for_registered_peer(reg_dir):
    register_peer(AgentIdentity(agent_id="chimera-alpha"))
    state = lookup_peer_state("chimera-alpha")
    assert state is not None
    assert state["plan_kfm_state"] == "STABLE"
    assert state["trust_tier_int"] == 2


def test_lookup_peer_state_none_for_unknown_peer(reg_dir):
    assert lookup_peer_state("chimera-ghost") is None


# ── HTTP middleware sets contextvar ────────────────────────


@pytest.fixture
def http_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(
        "CHIMERA_PEER_TOKENS", '{"alpha-token": "chimera-alpha"}'
    )
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    return build_http_app(cms)


def test_unknown_token_rejected_with_401(http_app):
    with TestClient(http_app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401


def test_known_token_passes_auth(http_app):
    """Token map alone is sufficient for auth."""
    with TestClient(http_app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer alpha-token"},
        )
        # Not 401 (auth passed). Whatever MCP returns next is fine for this check.
        assert resp.status_code != 401


def test_both_shared_token_and_peer_map_work(monkeypatch, tmp_path):
    """CHIMERA_PEER_TOKEN (shared) + CHIMERA_PEER_TOKENS (per-peer) coexist."""
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "shared-secret")
    monkeypatch.setenv(
        "CHIMERA_PEER_TOKENS", '{"alpha-token": "chimera-alpha"}'
    )
    cms = ChimeraMCPServer.from_env(name="chimera-test")
    app = build_http_app(cms)
    with TestClient(app) as client:
        # Shared token works.
        r1 = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer shared-secret"},
        )
        assert r1.status_code != 401
        # Per-peer token works.
        r2 = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer alpha-token"},
        )
        assert r2.status_code != 401


# ── contextvar default is None at module import ────────────


def test_current_peer_defaults_to_none():
    assert current_peer.get() is None


# ── call_tool reads contextvar ──────────────────────────────


@pytest.mark.asyncio
async def test_call_tool_uses_attested_peer_for_session_id(monkeypatch, tmp_path, reg_dir):
    """When a peer is attested, the session_id reflects it (T2 if registry-known)."""
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    register_peer(AgentIdentity(agent_id="chimera-alpha"))
    cms = ChimeraMCPServer.from_env(name="chimera-test")

    # Inject a captured-context tool.
    captured = []

    async def _capture(args, ctx):
        captured.append((ctx.trust_tier, ctx.session_id))
        return "ok"

    cms.registry.register(
        name="capture",
        toolset="peer",
        schema={
            "type": "function",
            "function": {"name": "capture", "description": "", "parameters": {"type": "object", "properties": {}}},
        },
        handler=_capture,
        override=True,
    )
    # Mark this tool as exposed by rebuilding the server with an expanded
    # allow-list. Easier: directly inject into the existing exposed frozenset
    # via the build_server path on a fresh server.
    from chimera.server.mcp_server import build_server
    new_exposed = frozenset(cms.exposed | {"capture"})
    test_server = build_server(
        name="chimera-test",
        registry=cms.registry,
        dispatcher=cms.dispatcher,
        exposed=new_exposed,
    )

    # Set the contextvar as if the middleware did so.
    token_ctx = current_peer.set("chimera-alpha")
    try:
        handler = test_server.request_handlers[mt.CallToolRequest]
        req = mt.CallToolRequest(
            method="tools/call",
            params=mt.CallToolRequestParams(name="capture", arguments={}),
        )
        await handler(req)
    finally:
        current_peer.reset(token_ctx)

    assert captured == [("T2", "peer:chimera-alpha")]


@pytest.mark.asyncio
async def test_call_tool_falls_back_to_t1_when_peer_unknown(monkeypatch, tmp_path, reg_dir):
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env(name="chimera-test")

    captured = []

    async def _capture(args, ctx):
        captured.append((ctx.trust_tier, ctx.session_id))
        return "ok"

    cms.registry.register(
        name="capture2",
        toolset="peer",
        schema={
            "type": "function",
            "function": {"name": "capture2", "description": "", "parameters": {"type": "object", "properties": {}}},
        },
        handler=_capture,
        override=True,
    )
    from chimera.server.mcp_server import build_server
    test_server = build_server(
        name="chimera-test",
        registry=cms.registry,
        dispatcher=cms.dispatcher,
        exposed=frozenset(cms.exposed | {"capture2"}),
    )

    # Peer name set but NOT in registry.
    token_ctx = current_peer.set("chimera-unknown")
    try:
        handler = test_server.request_handlers[mt.CallToolRequest]
        req = mt.CallToolRequest(
            method="tools/call",
            params=mt.CallToolRequestParams(name="capture2", arguments={}),
        )
        await handler(req)
    finally:
        current_peer.reset(token_ctx)

    assert captured == [("T1", "peer:chimera-unknown")]


@pytest.mark.asyncio
async def test_call_tool_anonymous_path_unchanged(monkeypatch, tmp_path):
    """No peer set → flat T1 / session_id='peer' from v2.0."""
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_PEER_EXPOSED_TOOLS", "")
    cms = ChimeraMCPServer.from_env(name="chimera-test")

    captured = []

    async def _capture(args, ctx):
        captured.append((ctx.trust_tier, ctx.session_id))
        return "ok"

    cms.registry.register(
        name="capture3",
        toolset="peer",
        schema={
            "type": "function",
            "function": {"name": "capture3", "description": "", "parameters": {"type": "object", "properties": {}}},
        },
        handler=_capture,
        override=True,
    )
    from chimera.server.mcp_server import build_server
    test_server = build_server(
        name="chimera-test",
        registry=cms.registry,
        dispatcher=cms.dispatcher,
        exposed=frozenset(cms.exposed | {"capture3"}),
    )

    handler = test_server.request_handlers[mt.CallToolRequest]
    req = mt.CallToolRequest(
        method="tools/call",
        params=mt.CallToolRequestParams(name="capture3", arguments={}),
    )
    await handler(req)
    assert captured == [("T1", "peer")]
