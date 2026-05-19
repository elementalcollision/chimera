"""Tests for behavioral drift detector + stagnation detector."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.drift import (
    DriftConfig,
    DriftDetector,
    Outcome,
    StagnationConfig,
    detect_stagnation,
)


# ── Behavioral drift detector ────────────────────────────────


def _feed_words(d: DriftDetector, words: list[str], tools: list[str] | None = None):
    """Feed one observation per word — keeps counts proportional to inputs."""
    for w in words:
        d.observe(w, tools=tools)


def test_no_anchor_means_zero_drift():
    d = DriftDetector()
    _feed_words(d, ["alpha"] * 10)
    assert d.should_assess()
    reading = d.assess()
    assert reading.composite_score == 0.0
    assert reading.severity == "low"


def test_identical_observations_after_boundary_score_zero():
    d = DriftDetector()
    _feed_words(d, ["alpha", "beta", "gamma"] * 4, tools=["shell"])
    d.mark_boundary()
    _feed_words(d, ["alpha", "beta", "gamma"] * 4, tools=["shell"])
    for _ in range(d.config.assessment_interval):
        d.observe("alpha", tools=["shell"])
    reading = d.assess()
    assert reading.instrument_scores["ghost_lexicon"] == 0.0


def test_vocabulary_loss_drives_ghost_score():
    d = DriftDetector()
    # Anchor period: a rich vocabulary.
    _feed_words(d, ["alpha", "beta", "gamma", "delta", "epsilon"])
    d.mark_boundary()
    # Post-boundary: a single recurring word; the anchor vocab is "lost".
    for _ in range(10):
        d.observe("alpha")
    reading = d.assess()
    # 4 of 5 anchor words are absent now.
    assert reading.instrument_scores["ghost_lexicon"] == pytest.approx(0.8, abs=0.01)


def test_tool_distribution_shift_drives_behavioral_score():
    d = DriftDetector()
    # Anchor: all calls were to "shell".
    for _ in range(10):
        d.observe("text here", tools=["shell"])
    d.mark_boundary()
    # Post-boundary: all calls are to "edit". Complete redirection.
    for _ in range(10):
        d.observe("text here", tools=["edit"])
    reading = d.assess()
    assert reading.instrument_scores["behavioral_footprint"] == pytest.approx(1.0)


def test_lockdown_severity_triggers_above_threshold():
    d = DriftDetector(config=DriftConfig(min_observations=1, assessment_interval=1))
    for _ in range(5):
        d.observe("alpha beta gamma delta epsilon", tools=["shell"])
    d.mark_boundary()
    for _ in range(5):
        d.observe("zzz", tools=["edit"])
    reading = d.assess()
    assert reading.severity == "high"
    assert reading.composite_score >= 0.30


def test_should_assess_respects_min_and_interval():
    d = DriftDetector(config=DriftConfig(min_observations=5, assessment_interval=10))
    for _ in range(4):
        d.observe("x")
        assert not d.should_assess()
    for _ in range(6):
        d.observe("x")
    # 10 observations: at threshold, interval %.
    assert d.should_assess()


def test_drift_state_persists_across_reload(tmp_path: Path):
    path = tmp_path / "drift" / "sess1.json"
    d1 = DriftDetector(state_path=path)
    _feed_words(d1, ["alpha", "beta", "gamma"] * 4, tools=["shell"])
    d1.mark_boundary()
    d1.observe("alpha")
    d1.save()

    d2 = DriftDetector(state_path=path)
    assert d2.observation_count == d1.observation_count
    assert d2.boundary_marked is True


def test_readings_retained_with_cap():
    d = DriftDetector(config=DriftConfig(min_observations=1, assessment_interval=1))
    d.observe("seed")
    d.mark_boundary()
    for i in range(120):
        d.observe(f"word{i}")
        d.assess()
    assert len(d.readings) == 100  # capped at 100


# ── Stagnation detector ──────────────────────────────────────


def _outs(buckets: list[str], kept_indices: set[int]) -> list[Outcome]:
    return [Outcome(bucket=b, kept=(i in kept_indices)) for i, b in enumerate(buckets)]


def test_stagnation_returns_none_for_short_history():
    history = _outs(["shell"] * 5, set())
    assert detect_stagnation(history) is None


def test_stagnation_returns_none_when_kept_above_threshold():
    # 15 items, all "shell", but 3 kept — kept > max_kept_for_stagnation.
    history = _outs(["shell"] * 15, {0, 7, 14})
    assert detect_stagnation(history) is None


def test_stagnation_returns_nudge_for_saturated_bucket_low_success():
    # 15 items, 12 "shell" + 3 "edit", only 1 kept.
    buckets = ["shell"] * 12 + ["edit"] * 3
    history = _outs(buckets, {0})
    nudge = detect_stagnation(history)
    assert nudge is not None
    assert "'shell'" in nudge
    assert "edit" in nudge  # alternative mentioned


def test_stagnation_respects_window():
    # Long history; only the tail matters.
    buckets = ["edit"] * 100 + ["shell"] * 12 + ["edit"] * 3
    history = _outs(buckets, {0, 50})  # earlier keeps; tail still stagnant
    nudge = detect_stagnation(history)
    assert nudge is not None
    assert "'shell'" in nudge


def test_stagnation_returns_none_when_bucket_not_saturated():
    # 15 items, evenly split — no bucket reaches bucket_saturation.
    buckets = ["shell"] * 7 + ["edit"] * 8
    history = _outs(buckets, set())
    nudge = detect_stagnation(history, StagnationConfig(bucket_saturation=12))
    assert nudge is None


def test_stagnation_custom_config():
    # Tighter window: only 5 items, all "shell", zero kept, saturation=3.
    history = _outs(["shell"] * 5, set())
    nudge = detect_stagnation(
        history, StagnationConfig(window=5, max_kept_for_stagnation=0, bucket_saturation=3)
    )
    assert nudge is not None and "'shell'" in nudge
