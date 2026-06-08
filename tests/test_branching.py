"""Tests for ADR 0171 subcriticality fan-out budget."""

from __future__ import annotations

import pytest

from chimera.core.branching import (
    expected_branching_total,
    fanout_budget_enabled,
    fanout_max_width,
    fanout_split,
    is_subcritical,
    subcritical_depth_budget,
)


# ── flag / config parsing ───────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_FANOUT_BUDGET", raising=False)
    assert fanout_budget_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "On", "yes"])
def test_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_FANOUT_BUDGET", val)
    assert fanout_budget_enabled() is True


def test_max_width_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_FANOUT_MAX_WIDTH", raising=False)
    assert fanout_max_width() == 8


def test_max_width_parsed(monkeypatch):
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "3")
    assert fanout_max_width() == 3


def test_max_width_floored_at_one(monkeypatch):
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "0")
    assert fanout_max_width() == 1


def test_max_width_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("CHIMERA_FANOUT_MAX_WIDTH", "wide")
    assert fanout_max_width() == 8


# ── fanout_split ────────────────────────────────────────────


def test_fanout_split_under_budget_dispatches_all():
    assert fanout_split(3, 8) == (3, 0)


def test_fanout_split_over_budget_defers_rest():
    assert fanout_split(12, 8) == (8, 4)


def test_fanout_split_exact_budget():
    assert fanout_split(8, 8) == (8, 0)


def test_fanout_split_floors_width_at_one():
    assert fanout_split(5, 0) == (1, 4)


def test_fanout_split_zero_width():
    assert fanout_split(0, 8) == (0, 0)


# ── is_subcritical ──────────────────────────────────────────


def test_subcritical_below_one():
    assert is_subcritical(mu=2.0, p_continue=0.4) is True   # 0.8 < 1
    assert is_subcritical(mu=1.0, p_continue=0.5) is True


def test_supercritical_at_or_above_one():
    assert is_subcritical(mu=2.0, p_continue=0.5) is False  # 1.0 not < 1
    assert is_subcritical(mu=3.0, p_continue=0.5) is False


# ── expected_branching_total ────────────────────────────────


def test_expected_total_mu_one_is_linear():
    # μ = 1 ⇒ one node per level ⇒ depth+1 total.
    assert expected_branching_total(1.0, 3) == pytest.approx(4.0)


def test_expected_total_geometric():
    # μ = 2, depth 2 ⇒ 1 + 2 + 4 = 7.
    assert expected_branching_total(2.0, 2) == pytest.approx(7.0)


def test_expected_total_negative_depth_zero():
    assert expected_branching_total(2.0, -1) == 0.0


def test_expected_total_grows_with_mu():
    assert expected_branching_total(3.0, 2) > expected_branching_total(2.0, 2)


# ── subcritical_depth_budget ────────────────────────────────


def test_depth_budget_subcritical_uses_hard_cap():
    # μ ≤ 1 ⇒ already bounded at any depth ⇒ full hard cap.
    assert subcritical_depth_budget(0.8, hard_cap=5) == 5
    assert subcritical_depth_budget(1.0, hard_cap=5) == 5


def test_depth_budget_cheaper_branching_earns_more_depth():
    # Smaller μ (cheaper branching) ⇒ at least as much depth as larger μ.
    low_mu = subcritical_depth_budget(1.5, hard_cap=10)
    high_mu = subcritical_depth_budget(5.0, hard_cap=10)
    assert low_mu >= high_mu
    assert high_mu >= 1


def test_depth_budget_never_exceeds_hard_cap():
    assert subcritical_depth_budget(1.1, hard_cap=2) <= 2
