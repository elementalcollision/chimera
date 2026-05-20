"""v4.72 (ADR 0091, P5) — selective per-engine enable in the scheduler."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from chimera.engines.scheduler import (
    EngineScheduler,
    engine_enable_snapshot,
)


@pytest.fixture
def scheduler(tmp_path: Path) -> EngineScheduler:
    return EngineScheduler(
        tmp_path / "last_runs.json",
        discovery_hour=8,
        curiosity_hour=14,
        reflection_hour=22,
    )


def _at(hour: int) -> dt.datetime:
    return dt.datetime(2026, 5, 20, hour, 30, tzinfo=dt.timezone.utc)


# ── snapshot defaults ──────────────────────────────────────────


def test_snapshot_default_all_on(monkeypatch):
    for k in (
        "CHIMERA_DISCOVERY_ENABLED",
        "CHIMERA_CURIOSITY_ENABLED",
        "CHIMERA_REFLECTION_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)
    snap = engine_enable_snapshot()
    assert snap == {"discovery": True, "curiosity": True, "reflection": True}


def test_snapshot_picks_up_per_engine_off(monkeypatch):
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("CHIMERA_CURIOSITY_ENABLED", "1")
    monkeypatch.delenv("CHIMERA_REFLECTION_ENABLED", raising=False)
    snap = engine_enable_snapshot()
    assert snap == {"discovery": False, "curiosity": True, "reflection": True}


# ── pick_due routing respects per-engine flag ──────────────────


def test_discovery_disabled_skips_morning(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "0")
    assert scheduler.pick_due(now=_at(9)) is None


def test_curiosity_disabled_skips_midday(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_CURIOSITY_ENABLED", "0")
    assert scheduler.pick_due(now=_at(15)) is None


def test_reflection_disabled_skips_evening(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_REFLECTION_ENABLED", "0")
    assert scheduler.pick_due(now=_at(23)) is None


def test_other_windows_unaffected_when_one_disabled(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "0")
    monkeypatch.delenv("CHIMERA_CURIOSITY_ENABLED", raising=False)
    monkeypatch.delenv("CHIMERA_REFLECTION_ENABLED", raising=False)
    # Discovery window → None (disabled), curiosity window still fires.
    assert scheduler.pick_due(now=_at(9)) is None
    assert scheduler.pick_due(now=_at(15)) == "curiosity"
    assert scheduler.pick_due(now=_at(23)) == "reflection"


def test_global_kill_overrides_per_engine_on(monkeypatch, scheduler):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "1")
    assert scheduler.pick_due(now=_at(9)) is None


def test_force_bypasses_per_engine_flag(monkeypatch, scheduler):
    """`force=...` is the operator's manual override; it bypasses both
    the global kill and the per-engine flag, matching v1.1 semantics."""
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "0")
    assert scheduler.pick_due(now=_at(9), force="discovery") == "discovery"


def test_all_engines_on_unchanged_behaviour(monkeypatch, scheduler):
    """Sanity: nothing changes when the operator sets nothing."""
    for k in (
        "CHIMERA_ENGINES_ENABLED",
        "CHIMERA_DISCOVERY_ENABLED",
        "CHIMERA_CURIOSITY_ENABLED",
        "CHIMERA_REFLECTION_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)
    assert scheduler.pick_due(now=_at(9)) == "discovery"
    assert scheduler.pick_due(now=_at(15)) == "curiosity"
    assert scheduler.pick_due(now=_at(23)) == "reflection"
