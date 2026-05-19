"""Tests for v2.8 alignment ceremony — five strategies + aggregator."""

from __future__ import annotations

import pytest

from chimera.a2a import (
    AlignmentCeremony,
    AlignmentResult,
    CeremonyResult,
    capability_alignment,
    drift_alignment,
    kfm_state_alignment,
    schema_alignment,
    version_alignment,
)


# ── capability ──────────────────────────────────────────────


def test_capability_alignment_aligned_when_required_present():
    r = capability_alignment(
        {"capabilities": ["shell", "code_exec", "web_search"]},
        required=("shell", "code_exec"),
    )
    assert r.result is AlignmentResult.ALIGNED


def test_capability_alignment_failed_when_required_missing():
    r = capability_alignment(
        {"capabilities": ["shell"]},
        required=("shell", "spawn_sub_agent"),
    )
    assert r.result is AlignmentResult.FAILED
    assert "spawn_sub_agent" in r.reason


def test_capability_alignment_failed_when_identity_none():
    r = capability_alignment(None, required=("shell",))
    assert r.result is AlignmentResult.FAILED


# ── version ─────────────────────────────────────────────────


def test_version_alignment_aligned_on_same_major():
    r = version_alignment({"version": "2.7.1"}, local_version="2.0.0")
    assert r.result is AlignmentResult.ALIGNED


def test_version_alignment_drifted_on_different_majors():
    r = version_alignment({"version": "3.0.0"}, local_version="2.7.0")
    assert r.result is AlignmentResult.DRIFTED


def test_version_alignment_drifted_on_unparseable():
    r = version_alignment({"version": "not-a-version"}, local_version="2.0.0")
    assert r.result is AlignmentResult.DRIFTED


# ── kfm_state ───────────────────────────────────────────────


@pytest.mark.parametrize("ok_state", ["STABLE", "CANDIDATE"])
def test_kfm_state_aligned_for_ok_states(ok_state):
    r = kfm_state_alignment({"plan_kfm_state": ok_state})
    assert r.result is AlignmentResult.ALIGNED


@pytest.mark.parametrize("term_state", ["DEPRECATED", "ARCHIVED", "KILLED"])
def test_kfm_state_failed_for_terminal_states(term_state):
    r = kfm_state_alignment({"plan_kfm_state": term_state})
    assert r.result is AlignmentResult.FAILED


@pytest.mark.parametrize("mid_state", ["NEW", "EXPERIMENTAL", None])
def test_kfm_state_drifted_for_other_states(mid_state):
    r = kfm_state_alignment({"plan_kfm_state": mid_state})
    assert r.result is AlignmentResult.DRIFTED


def test_kfm_state_drifted_when_state_none():
    r = kfm_state_alignment(None)
    assert r.result is AlignmentResult.DRIFTED


# ── schema ──────────────────────────────────────────────────


def _schema(name, props):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "",
            "parameters": {"type": "object", "properties": {p: {"type": "string"} for p in props}},
        },
    }


def test_schema_alignment_aligned_when_param_sets_match():
    a = _schema("shell", ["argv", "cwd", "timeout_s"])
    b = _schema("shell", ["timeout_s", "argv", "cwd"])
    r = schema_alignment(a, b)
    assert r.result is AlignmentResult.ALIGNED


def test_schema_alignment_drifted_when_peer_has_extras():
    peer = _schema("shell", ["argv", "cwd", "timeout_s", "uid"])
    local = _schema("shell", ["argv", "cwd", "timeout_s"])
    r = schema_alignment(peer, local)
    assert r.result is AlignmentResult.DRIFTED


def test_schema_alignment_failed_when_peer_missing_local_param():
    peer = _schema("shell", ["argv"])
    local = _schema("shell", ["argv", "cwd"])
    r = schema_alignment(peer, local)
    assert r.result is AlignmentResult.FAILED


def test_schema_alignment_drifted_when_peer_none():
    r = schema_alignment(None, _schema("shell", ["argv"]))
    assert r.result is AlignmentResult.DRIFTED


# ── drift ───────────────────────────────────────────────────


def test_drift_alignment_aligned_below_threshold():
    r = drift_alignment({"last_drift_score": 0.10}, lockdown_threshold=0.30)
    assert r.result is AlignmentResult.ALIGNED


def test_drift_alignment_failed_at_threshold():
    r = drift_alignment({"last_drift_score": 0.30}, lockdown_threshold=0.30)
    assert r.result is AlignmentResult.FAILED


def test_drift_alignment_aligned_when_score_none():
    r = drift_alignment({"last_drift_score": None})
    assert r.result is AlignmentResult.ALIGNED


def test_drift_alignment_drifted_when_state_none():
    r = drift_alignment(None)
    assert r.result is AlignmentResult.DRIFTED


def test_drift_alignment_drifted_on_unparseable_score():
    r = drift_alignment({"last_drift_score": "nan-string"})
    assert r.result is AlignmentResult.DRIFTED


# ── ceremony ────────────────────────────────────────────────


def test_ceremony_all_aligned():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell",),
        local_version="2.8.0",
    )
    verdict = ceremony.run(
        peer_identity={"version": "2.7.0", "capabilities": ["shell", "code_exec"]},
        peer_state={"plan_kfm_state": "STABLE", "last_drift_score": 0.05},
    )
    assert verdict.result is CeremonyResult.ALIGNED
    assert all(r.result is AlignmentResult.ALIGNED for r in verdict.reports)


def test_ceremony_drifted_when_any_drifted_but_none_failed():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell",),
        local_version="2.0.0",
    )
    verdict = ceremony.run(
        peer_identity={"version": "3.0.0", "capabilities": ["shell"]},
        peer_state={"plan_kfm_state": "STABLE", "last_drift_score": 0.05},
    )
    assert verdict.result is CeremonyResult.DRIFTED


def test_ceremony_failed_when_any_failed():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell", "missing_cap"),
        local_version="2.0.0",
    )
    verdict = ceremony.run(
        peer_identity={"version": "2.0.0", "capabilities": ["shell"]},
        peer_state={"plan_kfm_state": "STABLE"},
    )
    assert verdict.result is CeremonyResult.FAILED
    assert any("missing_cap" in r.reason for r in verdict.reports)


def test_ceremony_includes_schema_when_pair_provided():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell",),
        local_version="2.0.0",
        schema_pair=(_schema("shell", ["argv"]), _schema("shell", ["argv"])),
    )
    verdict = ceremony.run(
        peer_identity={"version": "2.0.0", "capabilities": ["shell"]},
        peer_state={"plan_kfm_state": "STABLE", "last_drift_score": 0.0},
    )
    assert verdict.result is CeremonyResult.ALIGNED
    strategies = {r.strategy for r in verdict.reports}
    assert "schema" in strategies


def test_ceremony_omits_schema_when_pair_not_provided():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell",),
        local_version="2.0.0",
    )
    verdict = ceremony.run(
        peer_identity={"version": "2.0.0", "capabilities": ["shell"]},
        peer_state={"plan_kfm_state": "STABLE", "last_drift_score": 0.0},
    )
    strategies = {r.strategy for r in verdict.reports}
    assert "schema" not in strategies
    assert strategies == {"capability", "version", "kfm_state", "drift"}


def test_ceremony_handles_none_payloads_gracefully():
    ceremony = AlignmentCeremony(
        required_capabilities=("shell",),
        local_version="2.0.0",
    )
    verdict = ceremony.run(peer_identity=None, peer_state=None)
    # capability + drift FAILED → overall FAILED.
    assert verdict.result is CeremonyResult.FAILED
