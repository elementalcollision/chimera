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


# ── v4.75: trust_state observer-mode warning ───────────────────────


def _write_heartbeat(mind_dir: Path, cycle: int) -> None:
    mind_dir.mkdir(parents=True, exist_ok=True)
    (mind_dir / "HEARTBEAT.md").write_text(
        f"---\ncycle: {cycle}\ntrust_tier: T0\nstatus: dormant\n---\nbody\n"
    )


def test_trust_state_ok_when_fresh_no_cycles(tmp_path):
    # No trust_state.json, no heartbeat → fresh install → ok.
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "ok"


def test_trust_state_warn_when_missing_after_cycles(monkeypatch, tmp_path):
    state_dir = tmp_path / "state_t0"
    mind_dir = tmp_path / "mind_t0"
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_heartbeat(mind_dir, cycle=7)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "warn"
    assert "trust promote" in r.message


def test_trust_state_warn_when_t0_after_cycles(monkeypatch, tmp_path):
    import json as _json
    state_dir = tmp_path / "state_locked"
    mind_dir = tmp_path / "mind_locked"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trust_state.json").write_text(_json.dumps({
        "current_tier": 0,
        "tier_entered_at": "2026-05-20T00:00:00+00:00",
        "last_readiness": 0.0,
        "history": [],
    }))
    _write_heartbeat(mind_dir, cycle=10)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "warn"
    assert "observer mode" in r.message


def test_trust_state_ok_when_promoted(monkeypatch, tmp_path):
    import json as _json
    state_dir = tmp_path / "state_unlocked"
    mind_dir = tmp_path / "mind_unlocked"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trust_state.json").write_text(_json.dumps({
        "current_tier": 2,
        "tier_entered_at": "2026-05-20T00:00:00+00:00",
        "last_readiness": 0.7,
        "history": [],
    }))
    _write_heartbeat(mind_dir, cycle=10)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "ok"
    assert "T2" in r.message


# ── v4.75: orphan WAL detection + checkpoint ───────────────────────


def test_wal_check_ok_when_no_wal_file(tmp_path, monkeypatch):
    """Fresh DB with no WAL → ok."""
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state_nowal"))
    r = _by_name(run_checks(), "wal")
    assert r.status == "ok"


def test_wal_check_warns_on_large_orphan_wal(tmp_path, monkeypatch):
    """Simulate a SIGKILL'd writer: a ≥1 MiB WAL with no live DB writer."""
    state_dir = tmp_path / "state_orphan"
    state_dir.mkdir(parents=True)
    db_path = state_dir / "chimera.db"
    import sqlite3
    sqlite3.connect(str(db_path)).close()
    (state_dir / "chimera.db-wal").write_bytes(b"\0" * (2 * 1024 * 1024))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    from chimera.core import doctor as _doctor
    monkeypatch.setattr(_doctor, "_has_active_writer", lambda _p: False)
    r = _by_name(run_checks(), "wal")
    assert r.status == "warn"
    assert "orphan WAL" in r.message
    assert "wal_checkpoint" in r.message


def test_checkpoint_wal_truncates_dirty_wal(tmp_path):
    """checkpoint_wal() leaves the WAL file at 0 bytes after committed writes."""
    from chimera.core import checkpoint_wal
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_fix"
    state_dir.mkdir(parents=True)
    conn = open_and_init(state_dir / "chimera.db")
    record_api_call(
        conn, cycle=1, provider="anthropic",
        model_id="claude-opus-4-7", input_tokens=100, output_tokens=10,
    )
    conn.commit()
    conn.close()
    ok, msg = checkpoint_wal(state_dir)
    assert ok, msg
    wal = state_dir / "chimera.db-wal"
    if wal.exists():
        assert wal.stat().st_size == 0, f"WAL not truncated: {wal.stat().st_size}"


def test_checkpoint_wal_noop_when_db_missing(tmp_path):
    from chimera.core import checkpoint_wal
    ok, msg = checkpoint_wal(tmp_path / "does_not_exist")
    assert ok is True
    assert "nothing to do" in msg


def test_shell_allowlist_warns_when_tool_missing_from_path(monkeypatch):
    """v4.80: doctor surfaces the gap when an advertised allow-list entry
    isn't on PATH so the operator can install it or accept the trim."""
    import chimera.core.doctor as doc_mod

    real_which = doc_mod.__dict__.get("shutil")  # not imported at module top
    import shutil as _shutil

    def fake_which(cmd: str) -> str | None:
        if cmd == "rg":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr(_shutil, "which", fake_which)
    result = _by_name(run_checks(), "shell_allowlist")
    assert result.status == "warn"
    assert "rg" in result.message


def test_shell_allowlist_ok_when_all_present(monkeypatch):
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    result = _by_name(run_checks(), "shell_allowlist")
    assert result.status == "ok"


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
