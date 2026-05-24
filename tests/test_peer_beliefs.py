"""Tests for the observer/observed belief module (ADR 0132)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.a2a.peer_beliefs import (
    PeerBelief,
    belief_from_kfm,
    default_journal_path,
    label_for_drift,
    latest_per_pair,
    list_beliefs,
    record_belief,
)


# ── label_for_drift mapping ───────────────────────────────────────


@pytest.mark.parametrize("score,expected", [
    (None, "UNKNOWN"),
    (0.0, "TRUSTS"),
    (0.29, "TRUSTS"),
    (0.30, "NEUTRAL"),
    (0.45, "NEUTRAL"),
    (0.59, "NEUTRAL"),
    (0.60, "DISTRUSTS"),
    (0.95, "DISTRUSTS"),
    (1.0, "DISTRUSTS"),
])
def test_label_for_drift_thresholds(score, expected):
    assert label_for_drift(score) == expected


def test_label_for_drift_clamps_out_of_range():
    assert label_for_drift(-0.5) == "TRUSTS"   # clamped to 0.0
    assert label_for_drift(2.0) == "DISTRUSTS"  # clamped to 1.0


def test_label_for_drift_non_numeric_returns_unknown():
    assert label_for_drift("not a number") == "UNKNOWN"


# ── belief_from_kfm ──────────────────────────────────────────────


def test_belief_from_kfm_distrusts_high_drift():
    kfm = {"cycle": 42, "trust_tier": "T1", "plan_kfm_state": "WORKING",
           "last_drift_score": 0.85}
    b = belief_from_kfm("alpha", kfm)
    assert b.observer == "alpha"
    assert b.observed == "alpha"  # self-belief in this PR's scope
    assert b.label == "DISTRUSTS"
    assert b.drift_score == 0.85
    assert b.source == "kfm"
    assert b.extra["cycle"] == 42
    assert b.extra["trust_tier"] == "T1"


def test_belief_from_kfm_unknown_when_no_score():
    b = belief_from_kfm("alpha", {"cycle": 1})
    assert b.label == "UNKNOWN"
    assert b.drift_score is None


# ── PeerBelief to_dict / from_dict ────────────────────────────────


def test_peer_belief_round_trip():
    b = PeerBelief(
        observer="alpha", observed="alpha",
        label="NEUTRAL", drift_score=0.4,
        recorded_at="2026-05-24T10:00:00+00:00", source="kfm",
        extra={"cycle": 5},
    )
    d = b.to_dict()
    assert d["label"] == "NEUTRAL"
    assert PeerBelief.from_dict(d) == b


def test_peer_belief_from_dict_safe_defaults():
    b = PeerBelief.from_dict({})
    assert b.observer == ""
    assert b.label == "UNKNOWN"
    assert b.source == "kfm"
    assert b.extra == {}


# ── JSONL persistence ────────────────────────────────────────────


def _make_belief(**kwargs):
    defaults = dict(
        observer="alpha", observed="alpha",
        label="TRUSTS", drift_score=0.1,
        recorded_at="2026-05-24T10:00:00+00:00", source="kfm",
        extra={},
    )
    defaults.update(kwargs)
    return PeerBelief(**defaults)


def test_record_belief_creates_file(tmp_path: Path):
    record_belief(_make_belief(), mind_dir=tmp_path)
    target = default_journal_path(tmp_path)
    assert target.exists()
    line = target.read_text().splitlines()[0]
    parsed = json.loads(line)
    assert parsed["observer"] == "alpha"
    assert parsed["label"] == "TRUSTS"


def test_record_belief_appends(tmp_path: Path):
    record_belief(_make_belief(observed="alpha"), mind_dir=tmp_path)
    record_belief(_make_belief(observed="beta"), mind_dir=tmp_path)
    lines = default_journal_path(tmp_path).read_text().splitlines()
    assert len(lines) == 2


def test_list_beliefs_returns_all(tmp_path: Path):
    record_belief(_make_belief(observer="alpha", observed="alpha"),
                  mind_dir=tmp_path)
    record_belief(_make_belief(observer="beta", observed="beta"),
                  mind_dir=tmp_path)
    out = list_beliefs(mind_dir=tmp_path)
    assert len(out) == 2
    assert {b.observer for b in out} == {"alpha", "beta"}


def test_list_beliefs_filters_by_observer(tmp_path: Path):
    record_belief(_make_belief(observer="alpha"), mind_dir=tmp_path)
    record_belief(_make_belief(observer="beta"), mind_dir=tmp_path)
    out = list_beliefs(mind_dir=tmp_path, observer="alpha")
    assert len(out) == 1
    assert out[0].observer == "alpha"


def test_list_beliefs_empty_when_no_journal(tmp_path: Path):
    assert list_beliefs(mind_dir=tmp_path) == []


def test_list_beliefs_skips_malformed_lines(tmp_path: Path):
    """Half-written / corrupt lines must not break the reader."""
    target = default_journal_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '{"observer": "alpha", "observed": "alpha", "label": "TRUSTS", '
        '"drift_score": 0.1, "recorded_at": "2026-05-24T10:00:00+00:00"}\n'
        '{not valid json\n'
        '\n'
        '[1, 2, 3]\n'  # top-level non-dict skipped
        '{"observer": "beta", "observed": "beta", "label": "DISTRUSTS"}\n'
    )
    out = list_beliefs(mind_dir=tmp_path)
    assert len(out) == 2
    assert {b.observer for b in out} == {"alpha", "beta"}


def test_latest_per_pair_picks_most_recent(tmp_path: Path):
    record_belief(_make_belief(
        observer="alpha", observed="alpha",
        recorded_at="2026-05-24T09:00:00+00:00", label="NEUTRAL",
    ), mind_dir=tmp_path)
    record_belief(_make_belief(
        observer="alpha", observed="alpha",
        recorded_at="2026-05-24T11:00:00+00:00", label="DISTRUSTS",
    ), mind_dir=tmp_path)
    record_belief(_make_belief(
        observer="beta", observed="beta",
        recorded_at="2026-05-24T10:00:00+00:00", label="TRUSTS",
    ), mind_dir=tmp_path)
    latest = latest_per_pair(mind_dir=tmp_path)
    assert latest[("alpha", "alpha")].label == "DISTRUSTS"
    assert latest[("beta", "beta")].label == "TRUSTS"
    assert len(latest) == 2


# ── Loop integration (ROTATE-phase ingest) ───────────────────────


@pytest.fixture
def loop(tmp_path: Path):
    from chimera.core import ChimeraLoop, LoopConfig

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    return ChimeraLoop(LoopConfig(mind_dir=mind, state_dir=state))


def test_ingest_safe_no_peers(loop, tmp_path: Path, monkeypatch):
    """Empty registry → no journal written, no exception."""
    monkeypatch.delenv("CHIMERA_PEER_BELIEFS_ON_ROTATE", raising=False)
    loop._ingest_peer_beliefs_safe()
    assert not default_journal_path(tmp_path / "mind").exists()


def test_ingest_safe_env_opt_out(loop, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_BELIEFS_ON_ROTATE", "0")
    # Force a path that would otherwise discover peers.
    monkeypatch.setattr(
        "chimera.a2a.peers.list_peer_chimeras",
        lambda registry=None: ["alpha"],
    )
    loop._ingest_peer_beliefs_safe()
    assert not default_journal_path(tmp_path / "mind").exists()


def test_ingest_safe_records_one_belief_per_peer(
    loop, tmp_path: Path, monkeypatch,
):
    monkeypatch.delenv("CHIMERA_PEER_BELIEFS_ON_ROTATE", raising=False)
    monkeypatch.setattr(
        "chimera.a2a.peers.list_peer_chimeras",
        lambda registry=None: ["alpha", "beta"],
    )

    async def fake_fetch(name, *, registry=None):
        return {"cycle": 1, "trust_tier": "T2",
                "plan_kfm_state": "WORKING",
                "last_drift_score": 0.1 if name == "alpha" else 0.7}

    monkeypatch.setattr("chimera.a2a.peers.fetch_peer_kfm", fake_fetch)
    loop._ingest_peer_beliefs_safe()

    beliefs = list_beliefs(mind_dir=tmp_path / "mind")
    assert {b.observer for b in beliefs} == {"alpha", "beta"}
    by_observer = {b.observer: b for b in beliefs}
    assert by_observer["alpha"].label == "TRUSTS"
    assert by_observer["beta"].label == "DISTRUSTS"


def test_ingest_safe_per_peer_failure_isolated(
    loop, tmp_path: Path, monkeypatch,
):
    """A failing fetch on peer A must not stop peer B."""
    monkeypatch.delenv("CHIMERA_PEER_BELIEFS_ON_ROTATE", raising=False)
    monkeypatch.setattr(
        "chimera.a2a.peers.list_peer_chimeras",
        lambda registry=None: ["bad", "good"],
    )

    async def fake_fetch(name, *, registry=None):
        if name == "bad":
            raise RuntimeError("peer unreachable")
        return {"last_drift_score": 0.2}

    monkeypatch.setattr("chimera.a2a.peers.fetch_peer_kfm", fake_fetch)
    loop._ingest_peer_beliefs_safe()  # must not raise
    beliefs = list_beliefs(mind_dir=tmp_path / "mind")
    assert len(beliefs) == 1
    assert beliefs[0].observer == "good"


# ── ADR 0132 doc presence ─────────────────────────────────────────


def test_adr_0132_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0132-observer-observed-beliefs.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "BELIEVES_ABOUT" in body
    assert "CHIMERA_PEER_BELIEFS_ON_ROTATE" in body
    assert "0128" in body
