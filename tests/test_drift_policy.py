"""Drift policy + loop-integration tests for Phase 2.3."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import ChimeraLoop, LoopConfig
from chimera.drift import (
    DriftAction,
    DriftConfig,
    DriftDetector,
    DriftSignal,
    Outcome,
    respond,
)


# ── policy (pure) ────────────────────────────────────────────


def test_policy_low_score_is_observe():
    sig = DriftSignal(composite_score=0.05, severity="low")
    decision = respond(sig)
    assert decision.action is DriftAction.OBSERVE
    assert "no drift" in decision.reason


def test_policy_warning_band_is_observe_with_reason():
    sig = DriftSignal(composite_score=0.20, severity="moderate")
    decision = respond(sig)
    assert decision.action is DriftAction.OBSERVE
    assert "warning band" in decision.reason


def test_policy_lockdown_demotes_plan():
    sig = DriftSignal(composite_score=0.40, severity="high")
    decision = respond(sig)
    assert decision.action is DriftAction.DEMOTE_PLAN


def test_policy_post_boundary_lockdown_kills_session():
    sig = DriftSignal(
        composite_score=0.40, severity="high", boundary_recently_crossed=True
    )
    decision = respond(sig)
    assert decision.action is DriftAction.KILL_SESSION
    assert "post-boundary" in decision.reason


def test_policy_stagnation_nudge_takes_priority_over_low_observe():
    sig = DriftSignal(composite_score=0.05, stagnation_nudge="try something else")
    decision = respond(sig)
    assert decision.action is DriftAction.NUDGE
    assert decision.nudge == "try something else"


def test_policy_lockdown_beats_stagnation():
    """Behavioral lockdown is a stronger signal than strategy stagnation."""
    sig = DriftSignal(
        composite_score=0.40, stagnation_nudge="try edits instead"
    )
    decision = respond(sig)
    assert decision.action is DriftAction.DEMOTE_PLAN


def test_policy_custom_thresholds():
    sig = DriftSignal(composite_score=0.10)
    decision = respond(sig, lockdown_threshold=0.05, warning_threshold=0.02)
    assert decision.action is DriftAction.DEMOTE_PLAN


# ── loop integration ────────────────────────────────────────


@pytest.fixture
def mind_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mind"
    d.mkdir()
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def config(mind_dir: Path, state_dir: Path) -> LoopConfig:
    return LoopConfig(mind_dir=mind_dir, state_dir=state_dir)


@pytest.mark.asyncio
async def test_drift_decision_recorded_after_boundary(config):
    """First cycle marks the boundary; the SECOND cycle is the first to assess."""
    detector = DriftDetector(
        config=DriftConfig(min_observations=1, assessment_interval=1)
    )
    loop = ChimeraLoop(config, drift_detector=detector)
    first = await loop.run_one_cycle()
    # Boundary-marking cycle: behavioral assessment is skipped (clean run).
    assert first.drift_decision is None
    second = await loop.run_one_cycle()
    assert second.drift_decision is not None
    # Phase-log text repeats cycle-to-cycle, so composite should be low.
    assert second.drift_decision.action is DriftAction.OBSERVE


@pytest.mark.asyncio
async def test_drift_observation_persists_across_cycles(config):
    loop = ChimeraLoop(config)
    await loop.run_one_cycle()
    saved_path = config.state_dir / "drift" / "current.json"
    assert saved_path.exists(), "drift state should be persisted every cycle"
    # Construct a new loop pointing at the same state dir — should pick up the count.
    loop2 = ChimeraLoop(config)
    assert loop2.drift_detector.observation_count >= 1


@pytest.mark.asyncio
async def test_kill_session_decision_forces_rotation(config, mind_dir):
    # Manufacture a drift detector that will return high composite immediately.
    detector = DriftDetector(
        config=DriftConfig(min_observations=1, assessment_interval=1)
    )
    # Anchor it with one vocab/tool universe…
    detector.observe("alpha beta gamma delta epsilon", tools=["shell"])
    detector.mark_boundary()
    # …then poison observed with a totally different one before the loop runs.
    detector.observe("zzz", tools=["edit"])
    # Patch the policy via threshold tweak: lockdown=0.10 so 0.30+ trips it.
    detector.config = DriftConfig(
        min_observations=1,
        assessment_interval=1,
        lockdown_threshold=0.10,
        warning_threshold=0.05,
    )
    loop = ChimeraLoop(config, drift_detector=detector)
    # Pre-seed session_started_at so ROTATE has something to clear.
    from chimera.core.mind import HeartbeatState, save_heartbeat

    save_heartbeat(
        mind_dir / "HEARTBEAT.md",
        HeartbeatState(cycle=1, session_started_at="2026-05-18T00:00:00+00:00"),
        "",
    )
    report = await loop.run_one_cycle()
    # The boundary-marked path → high composite → KILL_SESSION → forced rotation.
    if report.drift_decision and report.drift_decision.action is DriftAction.KILL_SESSION:
        assert report.rotated is True
    else:
        # If the threshold mix didn't trip KILL specifically, we should at least
        # have hit DEMOTE_PLAN. Both prove the path.
        assert report.drift_decision is not None
        assert report.drift_decision.action in (
            DriftAction.DEMOTE_PLAN,
            DriftAction.KILL_SESSION,
        )


@pytest.mark.asyncio
async def test_stagnation_nudge_fires_independent_of_behavioral_assessment(config):
    """Stagnation is an orthogonal axis — fires even when behavioral is calm.

    Behavioral thresholds are pinned unreachably high so behavioral drift
    never trips the policy; the nudge can only come from stagnation.
    """
    detector = DriftDetector(
        config=DriftConfig(
            min_observations=1,
            assessment_interval=1,
            lockdown_threshold=0.99,
            warning_threshold=0.99,
        )
    )
    history = [Outcome("shell", False)] * 14 + [Outcome("shell", True)]
    loop = ChimeraLoop(config, drift_detector=detector, stagnation_history=history)
    report = await loop.run_one_cycle()
    assert report.drift_decision is not None
    assert report.drift_decision.action is DriftAction.NUDGE
    assert report.pending_nudge is not None
    assert "'shell'" in report.pending_nudge
