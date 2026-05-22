"""Graduated trust decrements by escalation severity — ADR 0100 (v4.93).

Motivated by the soak v7 run-3 trust-collapse fixture:

    /Users/dave/chimera-soak-v7-2026-05-22-1331/state/trust_state.json

…where 3× ungrounded_citation + 1× scope_evasion (in v4.92's uniform-
demotion regime) drove T5 → T0 LOCKED before phase-2 could begin.
With the v4.93 table, the same sequence must NOT lock the agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.trust import TrustManager, TrustTier
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


@pytest.fixture
def trust_path(tmp_path: Path) -> Path:
    return tmp_path / "trust_state.json"


def _seed_t5(tm: TrustManager) -> None:
    tm.set_tier(TrustTier.T5, reason="seed for calibration test")


# ── table itself ────────────────────────────────────────────


def test_table_has_calibrated_deltas():
    """The v4.93 calibration table — splits severity from draft-quality."""
    assert FINISH_REASON_TRUST_DELTAS["silent_failure"] == 2
    assert FINISH_REASON_TRUST_DELTAS["scope_evasion"] == 2
    assert FINISH_REASON_TRUST_DELTAS["artifact_missing"] == 1
    assert FINISH_REASON_TRUST_DELTAS["fix_without_test"] == 1
    assert FINISH_REASON_TRUST_DELTAS["ungrounded_citation"] == 0
    assert FINISH_REASON_TRUST_DELTAS["max_rounds"] == 0
    assert FINISH_REASON_TRUST_DELTAS["length"] == 0


# ── per-reason behavior ─────────────────────────────────────


def test_ungrounded_citation_does_not_lock_t5(trust_path):
    """v4.83 catches the citation; model retries and grounds. Not a trust hit."""
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    for _ in range(5):
        demoted = tm.apply_finish_reason("ungrounded_citation")
        assert demoted == 0
    assert tm.tier is TrustTier.T5


def test_scope_evasion_decrements_two_tiers(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    demoted = tm.apply_finish_reason("scope_evasion")
    assert demoted == 2
    assert tm.tier is TrustTier.T3


def test_silent_failure_decrements_two_tiers(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("silent_failure") == 2
    assert tm.tier is TrustTier.T3


def test_artifact_missing_decrements_one_tier(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("artifact_missing") == 1
    assert tm.tier is TrustTier.T4


def test_fix_without_test_decrements_one_tier(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("fix_without_test") == 1
    assert tm.tier is TrustTier.T4


def test_max_rounds_and_length_do_not_demote(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("max_rounds") == 0
    assert tm.apply_finish_reason("length") == 0
    assert tm.tier is TrustTier.T5


def test_unknown_finish_reason_does_not_demote(trust_path):
    """Unknown signals must not silently drain trust."""
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("brand_new_signal_we_have_not_decided_on") == 0
    assert tm.tier is TrustTier.T5


def test_stop_does_not_demote(trust_path):
    """Clean completion is not in the table; must demote 0."""
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    assert tm.apply_finish_reason("stop") == 0
    assert tm.tier is TrustTier.T5


# ── floor + multi-tier ──────────────────────────────────────


def test_demote_clamps_at_t0(trust_path):
    """apply_finish_reason cannot wrap below T0."""
    tm = TrustManager(trust_path)
    tm.set_tier(TrustTier.T1, reason="seed")
    demoted = tm.apply_finish_reason("scope_evasion")  # delta=2
    assert demoted == 1  # only 1 actually applied
    assert tm.tier is TrustTier.T0


def test_history_records_each_demote_with_finish_reason(trust_path):
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    tm.apply_finish_reason("scope_evasion", reason_suffix="cycle 7")
    demote_events = [e for e in tm.state.history if e.kind == "demote"]
    assert len(demote_events) == 2
    assert "finish_reason=scope_evasion" in demote_events[0].reason
    assert "cycle 7" in demote_events[0].reason


# ── the soak v7 run-3 fixture ───────────────────────────────


def test_v7_run3_fixture_does_not_lock(trust_path):
    """The real escalation sequence from soak v7 run-3.

    Reference fixture:
        /Users/dave/chimera-soak-v7-2026-05-22-1331/state/chimera.db

    Sequence observed during phase-1 grounding investigation:
        - ungrounded_citation
        - ungrounded_citation
        - ungrounded_citation
        - scope_evasion

    Under v4.92 (uniform -1 per drift-triggered demote_plan), this
    collapsed T5 → T0 LOCKED. Under v4.93's table, three draft-quality
    signals contribute zero and a single scope_evasion costs two
    tiers — final tier T3, which is well above LOCKED.
    """
    tm = TrustManager(trust_path)
    _seed_t5(tm)
    tm.apply_finish_reason("ungrounded_citation")
    tm.apply_finish_reason("ungrounded_citation")
    tm.apply_finish_reason("ungrounded_citation")
    tm.apply_finish_reason("scope_evasion")
    assert tm.tier > TrustTier.T0, "v7 run-3 fixture must not lock under v4.93"
    assert tm.tier is TrustTier.T3
