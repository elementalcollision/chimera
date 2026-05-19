"""Tests for chimera.core.doctor (v3.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import ConfigError, assert_no_errors, run_checks


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    for env in (
        "CHIMERA_MCP_SERVERS",
        "CHIMERA_PEER_TOKENS",
        "CHIMERA_PEER_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)


def _by_name(results, name):
    return next(r for r in results if r.name == name)


def test_run_checks_returns_ok_for_default_local_dev():
    results = run_checks()
    assert _by_name(results, "state_dir").status == "ok"
    assert _by_name(results, "mind_dir").status == "ok"
    assert _by_name(results, "chimera.db").status == "ok"
    assert _by_name(results, "graph: kuzu").status == "ok"


def test_missing_provider_keys_warn_not_error():
    results = run_checks()
    anth = _by_name(results, "ANTHROPIC_API_KEY")
    openr = _by_name(results, "OPENROUTER_API_KEY")
    assert anth.status == "warn"
    assert openr.status == "warn"


def test_invalid_mcp_servers_json_is_error(monkeypatch):
    monkeypatch.setenv("CHIMERA_MCP_SERVERS", "{not json")
    results = run_checks()
    assert _by_name(results, "CHIMERA_MCP_SERVERS").status == "error"
    with pytest.raises(ConfigError):
        assert_no_errors(results)


def test_mcp_servers_non_object_is_error(monkeypatch):
    monkeypatch.setenv("CHIMERA_MCP_SERVERS", "[]")
    assert _by_name(run_checks(), "CHIMERA_MCP_SERVERS").status == "error"


def test_peer_tokens_valid_json_object_is_ok(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_TOKENS", '{"tok-a": "peer-1"}')
    assert _by_name(run_checks(), "CHIMERA_PEER_TOKENS").status == "ok"


def test_http_auth_warns_when_no_tokens():
    assert _by_name(run_checks(), "http auth").status == "warn"


def test_http_auth_ok_when_single_token_set(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "secret")
    assert _by_name(run_checks(), "http auth").status == "ok"


def test_assert_no_errors_passes_for_clean_config():
    # Provider keys are warns, not errors → passes.
    results = assert_no_errors()
    assert results  # non-empty
