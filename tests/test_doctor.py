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


# ── v4.67 (ADR 0086): cost_caps check ──────────────────────────────


def test_cost_caps_ok_with_empty_db():
    """Fresh state dir → empty DB → no spend → check returns ok.
    (The dir-writability + sqlite checks run before cost_caps and
    create an empty chimera.db, so we land on the $0-spend branch.)"""
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "ok"
    # Either branch is fine: no-db OR empty-db reports zero spend.
    assert "no chimera.db" in r.message or "$0.00" in r.message


def test_cost_caps_ok_when_under_50_pct(monkeypatch, tmp_path):
    """Seed a small spend; check should be ok and report percentage."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_seeded"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=0,  # ~$0.44 → 2% of $20
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "ok", r.message
    assert "60m spend" in r.message


def test_cost_caps_warn_when_above_50_pct(monkeypatch, tmp_path):
    """Spend ~75% of cap → warn."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_warn"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    # 1M opus input = $15 = 75% of the $20 default cap.
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn", r.message


def test_cost_caps_warn_with_over_marker(monkeypatch, tmp_path):
    """Spend > cap → warn with explicit OVER prefix."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_over"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=2_000_000, output_tokens=0,  # $30 > $20
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn"
    assert "OVER" in r.message


def test_cost_caps_warn_when_rolling_cap_disabled(monkeypatch, tmp_path):
    """Operator explicitly disabled the cap → warn (not silent ok)."""
    state_dir = tmp_path / "state_disabled"
    state_dir.mkdir(parents=True, exist_ok=True)
    from chimera.memory import open_and_init
    db = open_and_init(state_dir / "chimera.db")
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "0")
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn"
    assert "disabled" in r.message.lower()


def test_cost_caps_never_returns_error(monkeypatch, tmp_path):
    """Cost-cap state is operational, not config — even absurd spend
    should warn, not error."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_huge"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=100_000_000, output_tokens=10_000_000,
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status != "error"
