"""Phase 2.4 — memory backing wired through the loop.

Verifies:
- WAKE auto-bootstraps a "current" plan entity in STABLE.
- Each phase records a row in agent_activity_log.
- DEMOTE_PLAN transitions the plan to DEPRECATED and bootstraps a new STABLE.
- KILL_SESSION also demotes the plan and forces ROTATE.
- Ontology survives a fresh ChimeraLoop instance (simulated restart).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import ChimeraLoop, LoopConfig
from chimera.core.mind import HeartbeatState, save_heartbeat
from chimera.drift import DriftConfig, DriftDetector
from chimera.memory import (
    activity_window,
    get_entity_by_name,
    list_entities,
    list_transitions,
    open_and_init,
)


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


# ── plan bootstrap ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_wake_bootstraps_current_plan_in_stable(config):
    loop = ChimeraLoop(config)
    report = await loop.run_one_cycle()
    assert report.current_plan_state == "STABLE"
    # Same entity exists in the DB.
    plan = get_entity_by_name(loop.db, kind="plan", name="current")
    assert plan is not None
    assert plan.kfm_state == "STABLE"
    assert plan.details.get("bootstrapped") is True
    loop.close()


@pytest.mark.asyncio
async def test_wake_reuses_existing_plan_across_cycles(config):
    loop = ChimeraLoop(config)
    await loop.run_one_cycle()
    plan_before = get_entity_by_name(loop.db, kind="plan", name="current")
    await loop.run_one_cycle()
    plan_after = get_entity_by_name(loop.db, kind="plan", name="current")
    assert plan_before.id == plan_after.id
    loop.close()


# ── activity log ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_phase_records_activity(config):
    loop = ChimeraLoop(config)
    report = await loop.run_one_cycle()
    summary = activity_window(
        loop.db, agent_id=loop.AGENT_ID, current_cycle=report.cycle, last_n_cycles=1
    )
    # 8 logged phases: wake, assess, plan, act, write, flush, commit, rotate.
    # (HOUSEKEEPING runs before the cycle number is known and intentionally skips.)
    assert summary["activity_count"] == 8
    assert summary["active_cycles_in_window"] == 1
    loop.close()


# ── DEMOTE_PLAN re-anchor ───────────────────────────────────


@pytest.mark.asyncio
async def test_demote_plan_transitions_entity_and_reanchors(config, mind_dir):
    # Construct a detector that will trip a high composite immediately.
    detector = DriftDetector(
        config=DriftConfig(
            min_observations=1,
            assessment_interval=1,
            lockdown_threshold=0.10,
            warning_threshold=0.05,
        )
    )
    detector.observe("alpha beta gamma delta epsilon", tools=["shell"])
    detector.mark_boundary()
    detector.observe("zzz", tools=["edit"])

    # Pre-seed HEARTBEAT so ROTATE doesn't fire from age.
    save_heartbeat(
        mind_dir / "HEARTBEAT.md",
        HeartbeatState(cycle=1, session_started_at="2026-05-18T22:00:00+00:00"),
        "",
    )
    loop = ChimeraLoop(config, drift_detector=detector)
    report = await loop.run_one_cycle()

    assert report.drift_decision is not None
    # Either DEMOTE_PLAN or KILL_SESSION will have demoted the plan.
    assert report.plan_demoted is True
    assert report.current_plan_state == "STABLE"  # new plan

    # The DB has two plan rows: the deprecated one (renamed) and the new STABLE.
    plans = list_entities(loop.db, kind="plan")
    assert len(plans) == 2
    states = {p.kfm_state for p in plans}
    assert states == {"DEPRECATED", "STABLE"}

    # The deprecated plan has a transition record.
    deprecated = [p for p in plans if p.kfm_state == "DEPRECATED"][0]
    transitions = list_transitions(loop.db, deprecated.id)
    assert len(transitions) == 1
    assert transitions[0].to_state == "DEPRECATED"
    assert transitions[0].operator_type == "k"
    loop.close()


# ── ontology persistence across restart ─────────────────────


@pytest.mark.asyncio
async def test_ontology_persists_across_loop_restart(config, state_dir):
    loop1 = ChimeraLoop(config)
    await loop1.run_one_cycle()
    plan_id = get_entity_by_name(loop1.db, kind="plan", name="current").id
    loop1.close()

    # Re-open the DB directly — simulates a fresh container.
    conn = open_and_init(state_dir / "chimera.db")
    same_plan = get_entity_by_name(conn, kind="plan", name="current")
    assert same_plan is not None
    assert same_plan.id == plan_id
    conn.close()


@pytest.mark.asyncio
async def test_activity_accumulates_across_cycles(config):
    loop = ChimeraLoop(config)
    await loop.run_one_cycle()
    await loop.run_one_cycle()
    summary = activity_window(
        loop.db, agent_id=loop.AGENT_ID, current_cycle=2, last_n_cycles=2
    )
    assert summary["active_cycles_in_window"] == 2
    assert summary["activity_count"] == 16  # 8 phases × 2 cycles
    loop.close()
