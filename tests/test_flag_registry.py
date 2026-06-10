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
