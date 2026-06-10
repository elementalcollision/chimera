"""Tests for the TrustManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.trust import TrustManager, TrustTier


@pytest.fixture
def trust_path(tmp_path: Path) -> Path:
    return tmp_path / "trust_state.json"


# ── basics ──────────────────────────────────────────────────


def test_starts_at_t0(trust_path):
    tm = TrustManager(trust_path)
    assert tm.tier is TrustTier.T0
    assert tm.tier.label == "LOCKED"


def test_promote_one_step(trust_path):
    tm = TrustManager(trust_path)
    assert tm.promote(reason="initial bootstrap") is True
    assert tm.tier is TrustTier.T1


def test_promote_capped_at_t5(trust_path):
    tm = TrustManager(trust_path)
    for _ in range(10):
        tm.promote()
    assert tm.tier is TrustTier.T5
    assert tm.promote() is False  # no further


def test_demote_one_step(trust_path):
    tm = TrustManager(trust_path)
    tm.promote()
    tm.promote()
    assert tm.tier is TrustTier.T2
    assert tm.demote(reason="drift warning") is True
    assert tm.tier is TrustTier.T1


def test_demote_capped_at_t0(trust_path):
    tm = TrustManager(trust_path)
    assert tm.demote(reason="test") is False


def test_lockdown_goes_straight_to_t0(trust_path):
    tm = TrustManager(trust_path)
    for _ in range(3):
        tm.promote()
    assert tm.tier is TrustTier.T3
    assert tm.lockdown(reason="behavioural drift") is True
    assert tm.tier is TrustTier.T0


# ── persistence ─────────────────────────────────────────────


def test_state_persists_across_instances(trust_path):
    tm1 = TrustManager(trust_path)
    tm1.promote(reason="a")
    tm1.promote(reason="b")
    tm2 = TrustManager(trust_path)
    assert tm2.tier is TrustTier.T2
    assert len(tm2.state.history) == 2
    assert tm2.state.history[-1].reason == "b"


def test_history_capped_at_200(trust_path):
    tm = TrustManager(trust_path)
    for _ in range(220):
        tm.promote()
        tm.demote(reason="bounce")
    assert len(tm.state.history) == 200


# ── readiness scoring ───────────────────────────────────────


def test_readiness_perfect_inputs_score_one(trust_path):
    tm = TrustManager(trust_path)
    r = tm.readiness(drift_score=0.0, activity_rate=1.0, failure_rate=0.0)
    assert r == pytest.approx(1.0)


def test_readiness_worst_inputs_score_zero(trust_path):
    tm = TrustManager(trust_path)
    r = tm.readiness(drift_score=1.0, activity_rate=0.0, failure_rate=1.0)
    assert r == pytest.approx(0.0)


def test_readiness_clamps_out_of_range_values(trust_path):
    tm = TrustManager(trust_path)
    r = tm.readiness(drift_score=-2.0, activity_rate=5.0, failure_rate=-1.0)
    assert r == pytest.approx(1.0)


def test_readiness_updates_last_readiness(trust_path):
    tm = TrustManager(trust_path)
    r = tm.readiness(drift_score=0.1, activity_rate=0.8, failure_rate=0.1)
    assert tm.state.last_readiness == round(r, 4)


# ── auto-promotion ──────────────────────────────────────────


def test_autopromote_blocked_by_low_readiness(trust_path):
    tm = TrustManager(trust_path, promotion_threshold=0.7, min_dwell_seconds=0)
    assert tm.maybe_autopromote(readiness=0.5) is False
    assert tm.tier is TrustTier.T0


def test_autopromote_blocked_by_dwell(trust_path):
    tm = TrustManager(trust_path, promotion_threshold=0.5, min_dwell_seconds=3600)
    assert tm.maybe_autopromote(readiness=0.99) is False
    assert tm.tier is TrustTier.T0


def test_autopromote_fires_when_both_satisfied(trust_path):
    tm = TrustManager(trust_path, promotion_threshold=0.5, min_dwell_seconds=0)
    assert tm.maybe_autopromote(readiness=0.8, reason_suffix="test cycle") is True
    assert tm.tier is TrustTier.T1
    assert tm.state.history[-1].kind == "autopromote"
    assert "test cycle" in tm.state.history[-1].reason


# ── operator set_tier escape hatch (v4.75) ──────────────────


def test_set_tier_jumps_directly(trust_path):
    tm = TrustManager(trust_path)
    assert tm.set_tier(TrustTier.T5, reason="operator promotion") is True
    assert tm.tier is TrustTier.T5
    assert tm.state.history[-1].kind == "operator"
    assert tm.state.history[-1].from_tier == 0
    assert tm.state.history[-1].to_tier == 5


def test_set_tier_revoke_kind_recorded(trust_path):
    tm = TrustManager(trust_path)
    tm.set_tier(4, reason="bootstrap")
    assert tm.set_tier(0, reason="drift incident", kind="revoke") is True
    assert tm.tier is TrustTier.T0
    assert tm.state.history[-1].kind == "revoke"


def test_set_tier_noop_returns_false(trust_path):
    tm = TrustManager(trust_path)
    assert tm.set_tier(0, reason="already there") is False
    assert tm.state.history == []


def test_set_tier_rejects_out_of_range(trust_path):
    tm = TrustManager(trust_path)
    with pytest.raises(ValueError):
        tm.set_tier(9, reason="bogus")
    with pytest.raises(ValueError):
        tm.set_tier(-1, reason="bogus")


def test_set_tier_persists(trust_path):
    tm1 = TrustManager(trust_path)
    tm1.set_tier(TrustTier.T3, reason="operator")
    tm2 = TrustManager(trust_path)
    assert tm2.tier is TrustTier.T3


def test_autopromote_capped_at_t5(trust_path):
    tm = TrustManager(trust_path, promotion_threshold=0.0, min_dwell_seconds=0)
    for _ in range(10):
        tm.maybe_autopromote(readiness=1.0)
    assert tm.tier is TrustTier.T5
    assert tm.maybe_autopromote(readiness=1.0) is False


# ── apply_finish_reason: v4.116 charter_file_count (ADR 0116) ──


def test_apply_finish_reason_charter_file_count_demotes_one_tier(trust_path):
    """v4.116: charter_file_count must demote one tier (v4.115 pattern)."""
    tm = TrustManager(trust_path)
    tm.promote(reason="bootstrap")
    tm.promote(reason="bootstrap")
    assert tm.tier is TrustTier.T2

    demoted = tm.apply_finish_reason("charter_file_count")

    assert demoted == 1
    assert tm.tier is TrustTier.T1
    assert tm.state.history[-1].kind == "demote"
    assert "charter_file_count" in tm.state.history[-1].reason


def test_apply_finish_reason_charter_file_count_clamps_at_t0(trust_path):
    """charter_file_count at T0 still returns 0 (clamped, not negative)."""
    tm = TrustManager(trust_path)
    assert tm.tier is TrustTier.T0
    assert tm.apply_finish_reason("charter_file_count") == 0


def test_readiness_gate_signal_blends_and_is_backward_compatible(tmp_path):
    """ADR 0163 follow-up: a gate-approval track record is earned trust.
    None preserves the pure operational score; a low gate rate pulls readiness
    down even when operational signals are perfect, and a high rate lifts it."""
    tm = TrustManager(tmp_path / "t.json")  # gate_weight default 0.3
    base = tm.readiness(drift_score=0.0, activity_rate=1.0, failure_rate=0.0)
    assert base == 1.0  # perfect operational, no gate history → unchanged
    # All operational signals perfect, but the agent's gate record is poor.
    low = tm.readiness(drift_score=0.0, activity_rate=1.0, failure_rate=0.0,
                       gate_approval_rate=0.0)
    assert low == pytest.approx(0.7)   # (1-0.3)*1.0 + 0.3*0.0
    # A strong gate record holds readiness high.
    high = tm.readiness(drift_score=0.0, activity_rate=1.0, failure_rate=0.0,
                        gate_approval_rate=1.0)
    assert high == pytest.approx(1.0)
    assert low < base  # earned-trust gating actually bites


def test_finish_reason_demotion_floors_at_t1(tmp_path):
    """Messy-process finish-reason churn must NOT cascade to T0 (observer
    lockdown) and self-lock the agent out of committing its faithful work
    (value-convergence 2026-06-03: T5→T0 in one build). T0 is reserved for the
    deliberate drift lockdown()."""
    import json
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"current_tier": 5}))
    tm = TrustManager(p)
    for _ in range(10):
        tm.apply_finish_reason("import_shadowing")
    assert tm.tier == TrustTier.T1   # floored, not T0
    # A higher-delta reason also floors at T1, not below.
    p.write_text(json.dumps({"current_tier": 5}))
    tm2 = TrustManager(p)
    for _ in range(10):
        tm2.apply_finish_reason("scope_evasion")
    assert tm2.tier == TrustTier.T1
    # Deliberate lockdown still reaches T0 (the drift safety path is unaffected).
    assert tm2.lockdown(reason="drift") is True
    assert tm2.tier == TrustTier.T0
