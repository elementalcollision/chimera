"""Tests for ADR 0170 entropy observability signals."""

from __future__ import annotations


import pytest

from chimera.core.entropy_signals import (
    entropy_of_labels,
    entropy_signals_enabled,
    normalized_entropy,
    proposal_diversity,
    shannon_entropy,
    tool_use_entropy,
    transition_entropy,
)


# ── flag parsing ────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_ENTROPY_SIGNALS", raising=False)
    assert entropy_signals_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "Yes", "on"])
def test_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_ENTROPY_SIGNALS", val)
    assert entropy_signals_enabled() is True


# ── shannon_entropy ─────────────────────────────────────────


def test_shannon_empty_and_singleton_are_zero():
    assert shannon_entropy([]) == 0.0
    assert shannon_entropy([5]) == 0.0
    assert shannon_entropy([0, 0]) == 0.0


def test_shannon_uniform_two_is_one_bit():
    assert shannon_entropy([1, 1]) == pytest.approx(1.0)


def test_shannon_uniform_four_is_two_bits():
    assert shannon_entropy([3, 3, 3, 3]) == pytest.approx(2.0)


def test_shannon_ignores_nonpositive_and_unnormalised():
    # 2:1 split — entropy is invariant to scale.
    assert shannon_entropy([2, 1]) == pytest.approx(shannon_entropy([20, 10]))
    assert shannon_entropy([1, 1, 0, -3]) == pytest.approx(1.0)


# ── normalized_entropy ──────────────────────────────────────


def test_normalized_uniform_is_one():
    assert normalized_entropy([1, 1, 1, 1]) == pytest.approx(1.0)


def test_normalized_fixation_is_low():
    # 97:1:1:1 — nearly all mass on one category.
    val = normalized_entropy([97, 1, 1, 1])
    assert 0.0 < val < 0.3


def test_normalized_singleton_is_zero():
    assert normalized_entropy([42]) == 0.0


# ── entropy_of_labels ───────────────────────────────────────


def test_entropy_of_labels_uniform():
    assert entropy_of_labels(["a", "b", "c", "d"]) == pytest.approx(1.0)


def test_entropy_of_labels_all_same_is_zero():
    assert entropy_of_labels(["x", "x", "x"]) == 0.0


# ── tool_use_entropy (fixation) ─────────────────────────────


def test_tool_use_entropy_fixation_low():
    fixated = ["shell"] * 9 + ["read"]
    diverse = ["shell", "read", "web_search", "code_exec"]
    assert tool_use_entropy(fixated) < tool_use_entropy(diverse)


def test_tool_use_entropy_single_tool_is_zero():
    assert tool_use_entropy(["shell", "shell", "shell"]) == 0.0


def test_tool_use_entropy_empty_is_zero():
    assert tool_use_entropy([]) == 0.0


# ── proposal_diversity ──────────────────────────────────────


def test_proposal_diversity_redundant_batch_is_low():
    # All four collapse to the same (basename, verb) cluster: append→notes.md.
    redundant = [
        "append a lesson to notes.md",
        "add the summary to notes.md",
        "append findings to notes.md",
        "append the note to notes.md",
    ]
    diverse = [
        "append a lesson to notes.md",
        "delete the stale entry from config.yaml",
        "fetch the schema from the registry",
        "run the regression suite",
    ]
    assert proposal_diversity(redundant) < proposal_diversity(diverse)


def test_proposal_diversity_distinct_clusters_high():
    diverse = [
        "edit config.toml",
        "delete old.json",
        "create report.md",
        "fetch data.txt",
    ]
    assert proposal_diversity(diverse) == pytest.approx(1.0)


# ── transition_entropy (stagnation) ─────────────────────────


def test_transition_entropy_stagnation_falls():
    # A varied transition window vs a stuck self-loop.
    varied = [("NEW", "CANDIDATE"), ("CANDIDATE", "STABLE"), ("STABLE", "ARCHIVED")]
    stuck = [("STABLE", "STABLE")] * 5
    assert transition_entropy(stuck) < transition_entropy(varied)
    assert transition_entropy(stuck) == 0.0
