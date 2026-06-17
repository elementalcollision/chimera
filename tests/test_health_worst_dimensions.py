"""Tests for HealthSummary.worst_dimensions()."""

from __future__ import annotations

from chimera.core.health import HealthDimension, HealthSummary


def _dim(key: str, status: str) -> HealthDimension:
    return HealthDimension(key, key.title(), status, f"{key} detail")


def test_mixed_red_and_amber_returns_only_red():
    s = HealthSummary(
        overall="red",
        dimensions=[_dim("drift", "red"), _dim("queue", "amber"), _dim("cost", "green")],
    )
    wd = s.worst_dimensions()
    assert len(wd) == 1
    assert wd[0].key == "drift"


def test_all_green_returns_empty():
    s = HealthSummary(
        overall="green",
        dimensions=[_dim("drift", "green"), _dim("queue", "green")],
    )
    assert s.worst_dimensions() == []


def test_unknown_overall_returns_empty():
    s = HealthSummary(
        overall="unknown",
        dimensions=[_dim("cost", "unknown"), _dim("drift", "unknown")],
    )
    assert s.worst_dimensions() == []


def test_multiple_red_dims_all_returned():
    s = HealthSummary(
        overall="red",
        dimensions=[_dim("drift", "red"), _dim("escalations", "red"), _dim("queue", "amber")],
    )
    wd = s.worst_dimensions()
    assert [d.key for d in wd] == ["drift", "escalations"]


def test_amber_overall_returns_amber_dims():
    s = HealthSummary(
        overall="amber",
        dimensions=[_dim("queue", "amber"), _dim("escalations", "amber"), _dim("drift", "green")],
    )
    keys = [d.key for d in s.worst_dimensions()]
    assert sorted(keys) == ["escalations", "queue"]
