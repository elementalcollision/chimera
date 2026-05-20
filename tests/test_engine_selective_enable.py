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


# ── session-relative mode (ADR 0092, v4.74) ────────────────────


def test_session_mode_fires_evening_session_curiosity(monkeypatch, scheduler):
    """The 2026-05-20 burn: evening PDT session lands in reflection's
    UTC window, so UTC-mode picks reflection. Session-mode fires
    discovery first (the priority head)."""
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    sess = "2026-05-20T19:33:22+00:00"
    # UTC-mode at 23:00 picks reflection. Session-mode picks discovery.
    assert scheduler.pick_due(now=_at(23), session_id=sess) == "discovery"


def test_session_mode_rotates_through_engines(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    sess = "session-alpha"
    # Cycle 1: discovery
    assert scheduler.pick_due(now=_at(23), session_id=sess) == "discovery"
    scheduler.mark_ran("discovery", session_id=sess)
    # Cycle 2: curiosity
    assert scheduler.pick_due(now=_at(23), session_id=sess) == "curiosity"
    scheduler.mark_ran("curiosity", session_id=sess)
    # Cycle 3: reflection
    assert scheduler.pick_due(now=_at(23), session_id=sess) == "reflection"
    scheduler.mark_ran("reflection", session_id=sess)
    # Cycle 4: all fired this session → nothing due
    assert scheduler.pick_due(now=_at(23), session_id=sess) is None


def test_session_mode_new_session_resets(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    scheduler.mark_ran("discovery", session_id="session-A")
    assert scheduler.pick_due(now=_at(23), session_id="session-A") == "curiosity"
    # New session — discovery becomes eligible again.
    assert scheduler.pick_due(now=_at(23), session_id="session-B") == "discovery"


def test_session_mode_respects_per_engine_disable(monkeypatch, scheduler):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    monkeypatch.setenv("CHIMERA_DISCOVERY_ENABLED", "0")
    # Discovery skipped; curiosity is next priority.
    assert scheduler.pick_due(now=_at(23), session_id="s") == "curiosity"


def test_session_mode_off_uses_utc_window(monkeypatch, scheduler):
    """When session mode is off (default), UTC-window logic runs even
    if session_id is supplied — backward compatibility."""
    monkeypatch.delenv("CHIMERA_ENGINE_SESSION_MODE", raising=False)
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    # 23:00 UTC = reflection window.
    assert scheduler.pick_due(now=_at(23), session_id="ignored") == "reflection"


def test_session_mode_no_session_id_falls_back_to_utc(monkeypatch, scheduler):
    """Session mode on but no session_id → falls through to UTC logic
    (defensive: the loop should always pass session_id, but if not,
    do something sensible)."""
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    assert scheduler.pick_due(now=_at(23)) == "reflection"


def test_session_mode_global_kill_still_wins(monkeypatch, scheduler):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    assert scheduler.pick_due(now=_at(23), session_id="s") is None


def test_mark_ran_session_mode_stores_both_keys(monkeypatch, scheduler):
    """mark_ran writes both the date key AND the session key so the
    operator can flip session mode on/off without losing history."""
    monkeypatch.setenv("CHIMERA_ENGINE_SESSION_MODE", "1")
    scheduler.mark_ran("discovery", session_id="session-X", now=_at(10))
    snap = scheduler.snapshot()
    assert snap["discovery"] == "2026-05-20"
    assert snap["session:discovery"] == "session-X"
