"""Registry-completeness + validation tests for chimera/config.py (ADR 0176).

The completeness test is the enforcement mechanism: every CHIMERA_* name
read anywhere in the package must be declared in config.REGISTRY (or match
a declared dynamic prefix), and every declared flag must still exist in the
source. Adding a flag without declaring it — or removing a flag and leaving
a stale declaration — fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from chimera import config

PACKAGE_ROOT = Path(config.__file__).parent

_FLAG_RE = re.compile(r"CHIMERA_[A-Z0-9_]+")


def _flags_in_source() -> set[str]:
    found: set[str] = set()
    for py in PACKAGE_ROOT.rglob("*.py"):
        if py.name == "config.py":
            continue  # the registry itself doesn't count as a read
        found.update(_FLAG_RE.findall(py.read_text(encoding="utf-8")))
    # Names that end at a dynamic-prefix boundary (e.g. the literal
    # "CHIMERA_PROPOSER_" inside an f-string) collapse to the prefix.
    return found


def _is_dynamic(name: str) -> bool:
    return any(
        name == p.rstrip("_") or name.startswith(p)
        for p in config.DYNAMIC_FLAG_PREFIXES
    )


def test_every_flag_in_source_is_declared():
    undeclared = {
        n for n in _flags_in_source()
        if n not in config.REGISTRY and not _is_dynamic(n)
    }
    assert undeclared == set(), (
        f"CHIMERA_* flags read in chimera/ but not declared in "
        f"chimera/config.py REGISTRY: {sorted(undeclared)}. "
        f"Declare them (kind, default, description) — and if they interact "
        f"with existing flags, add a validate_env rule."
    )


def test_every_declared_flag_exists_in_source():
    in_source = _flags_in_source()
    stale = {
        n for n in config.REGISTRY
        if n not in in_source
        and not any(s.startswith(n) for s in in_source)  # substring-prefix reads
    }
    assert stale == set(), (
        f"Flags declared in chimera/config.py REGISTRY but no longer read "
        f"anywhere in chimera/: {sorted(stale)}. Remove the stale declarations."
    )


def test_high_impact_flags_are_declared():
    missing = set(config.HIGH_IMPACT_FLAGS) - set(config.REGISTRY)
    assert missing == set()


def test_interacts_with_references_are_declared():
    for spec in config.REGISTRY.values():
        for other in spec.interacts_with:
            assert other in config.REGISTRY, (
                f"{spec.name}.interacts_with references undeclared flag {other}"
            )


# ── validate_env rules ──────────────────────────────────────


def test_validate_env_clean_environment_no_warnings():
    assert config.validate_env({}) == []


def test_validate_env_graph_legacy_override():
    warnings = config.validate_env(
        {"CHIMERA_GRAPH_ENABLED": "1", "CHIMERA_AUTO_GRAPH_UPDATE_DISABLED": "1"}
    )
    assert any("forces the graph projection OFF" in w for w in warnings)


def test_validate_env_archive_cycles_ignored_when_disabled():
    warnings = config.validate_env(
        {"CHIMERA_AUTO_ARCHIVE_DISABLED": "1", "CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES": "30"}
    )
    assert any("AUTO_ARCHIVE_AFTER_CYCLES is ignored" in w for w in warnings)


def test_validate_env_fanout_width_zero_warns():
    warnings = config.validate_env(
        {"CHIMERA_FANOUT_BUDGET": "1", "CHIMERA_FANOUT_MAX_WIDTH": "0"}
    )
    assert any("defer every parallel tool call" in w for w in warnings)


def test_validate_env_fanout_width_sane_no_warning():
    warnings = config.validate_env(
        {"CHIMERA_FANOUT_BUDGET": "1", "CHIMERA_FANOUT_MAX_WIDTH": "3"}
    )
    assert warnings == []


def test_validate_env_force_stall_without_run_id():
    warnings = config.validate_env({"CHIMERA_SOAK_FORCE_STALL": "1"})
    assert any("inert without CHIMERA_SOAK_RUN_ID" in w for w in warnings)


def test_validate_env_model_peer_vendors_without_model_peers():
    warnings = config.validate_env({"CHIMERA_MODEL_PEER_VENDORS": "deepseek"})
    assert any("ignored without CHIMERA_MODEL_PEERS" in w for w in warnings)


def test_validate_env_boltzmann_temp_without_alloc():
    warnings = config.validate_env({"CHIMERA_BOLTZMANN_TEMP": "1.5"})
    assert any("ignored without CHIMERA_BOLTZMANN_ALLOC" in w for w in warnings)


def test_validate_env_half_configured_tls_pair():
    warnings = config.validate_env({"CHIMERA_TLS_CERT": "/x/cert.pem"})
    assert any("must be set together" in w for w in warnings)
    warnings = config.validate_env({"CHIMERA_TLS_KEY": "/x/key.pem"})
    assert any("must be set together" in w for w in warnings)
    warnings = config.validate_env(
        {"CHIMERA_TLS_CERT": "/x/cert.pem", "CHIMERA_TLS_KEY": "/x/key.pem"}
    )
    assert not any("must be set together" in w for w in warnings)


def test_validate_env_bad_int_reported():
    warnings = config.validate_env({"CHIMERA_PLAN_MAX_OPEN_TASKS": "lots"})
    assert any("not an integer" in w for w in warnings)


def test_validate_env_bad_float_reported():
    warnings = config.validate_env({"CHIMERA_TASK_BUDGET_USD": "cheap"})
    assert any("not a number" in w for w in warnings)


def test_validate_env_bad_json_reported():
    warnings = config.validate_env({"CHIMERA_REMOTE_PEERS": "{not json"})
    assert any("not valid JSON" in w for w in warnings)


def test_validate_env_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("CHIMERA_SOAK_FORCE_STALL", "1")
    monkeypatch.delenv("CHIMERA_SOAK_RUN_ID", raising=False)
    assert any("inert" in w for w in config.validate_env())


# ── registry-backed read accessors ──────────────────────────


def test_flag_enabled_truthy_spellings(monkeypatch):
    for raw in ("1", "true", "YES", " on "):
        monkeypatch.setenv("CHIMERA_FANOUT_BUDGET", raw)
        assert config.flag_enabled("CHIMERA_FANOUT_BUDGET") is True
    for raw in ("0", "off", "no", "", "enabled"):
        monkeypatch.setenv("CHIMERA_FANOUT_BUDGET", raw)
        assert config.flag_enabled("CHIMERA_FANOUT_BUDGET") is False
    monkeypatch.delenv("CHIMERA_FANOUT_BUDGET")
    assert config.flag_enabled("CHIMERA_FANOUT_BUDGET") is False


def test_flag_accessors_refuse_undeclared_names():
    import pytest as _pytest

    with _pytest.raises(KeyError, match="not declared"):
        config.flag_enabled("CHIMERA_TOTALLY_MADE_UP")
    with _pytest.raises(KeyError, match="not declared"):
        config.flag_int("CHIMERA_TOTALLY_MADE_UP", 1)
    with _pytest.raises(KeyError, match="not declared"):
        config.flag_float("CHIMERA_TOTALLY_MADE_UP", 1.0)


def test_flag_accessors_allow_dynamic_prefixes():
    # Dynamic family names resolve without an exact registry entry.
    assert config.flag_int("CHIMERA_ACT_MAX_TOKENS_SONNET", 4096) == 4096


def test_flag_int_malformed_and_minimum(monkeypatch):
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "lots")
    assert config.flag_int("CHIMERA_FANOUT_MAX_WIDTH", 8, minimum=1) == 8
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "0")
    assert config.flag_int("CHIMERA_FANOUT_MAX_WIDTH", 8, minimum=1) == 1
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "3")
    assert config.flag_int("CHIMERA_FANOUT_MAX_WIDTH", 8, minimum=1) == 3


def test_flag_float_malformed_and_minimum(monkeypatch):
    monkeypatch.setenv("CHIMERA_BOLTZMANN_TEMP", "warm")
    assert config.flag_float("CHIMERA_BOLTZMANN_TEMP", 0.0, minimum=0.0) == 0.0
    monkeypatch.setenv("CHIMERA_BOLTZMANN_TEMP", "-2.5")
    assert config.flag_float("CHIMERA_BOLTZMANN_TEMP", 0.0, minimum=0.0) == 0.0
    monkeypatch.setenv("CHIMERA_BOLTZMANN_TEMP", "1.5")
    assert config.flag_float("CHIMERA_BOLTZMANN_TEMP", 0.0, minimum=0.0) == 1.5


def test_migrated_readers_delegate_to_registry(monkeypatch):
    """The ADR 0165–0174 family readers now resolve through the registry
    read path — same truthy semantics, same defaults."""
    from chimera.core.branching import fanout_budget_enabled, fanout_max_width

    monkeypatch.setenv("CHIMERA_FANOUT_BUDGET", "on")
    assert fanout_budget_enabled() is True
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "junk")
    assert fanout_max_width() == 8  # default survives malformed values


def test_loop_startup_logs_flag_warnings(tmp_path, monkeypatch, caplog):
    """ADR 0176: ChimeraLoop init surfaces validate_env warnings via logging
    (warn-only — misconfiguration must never block boot)."""
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "1")

    from chimera.core import ChimeraLoop, LoopConfig

    with caplog.at_level("WARNING", logger="chimera.core.loop"):
        ChimeraLoop(LoopConfig.from_env())
    assert any("flag config:" in r.getMessage() for r in caplog.records), (
        "expected a 'flag config:' warning for the graph legacy-override trap"
    )
