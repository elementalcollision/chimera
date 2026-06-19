"""Tests for HealthSummary.alert_line()."""

from __future__ import annotations

from chimera.core.health import HealthDimension, HealthSummary


def _dim(key: str, status: str) -> HealthDimension:
    return HealthDimension(key, key.title(), status, f"{key} detail")


def test_green_returns_ok():
    s = HealthSummary(
        overall="green",
        dimensions=[_dim("drift", "green"), _dim("queue", "green")],
    )
    assert s.alert_line() == "OK"


def test_unknown_returns_unknown():
    s = HealthSummary(
        overall="unknown",
        dimensions=[_dim("cost", "unknown"), _dim("drift", "unknown")],
    )
    assert s.alert_line() == "UNKNOWN"


def test_red_single_dim_returns_degraded():
    s = HealthSummary(
        overall="red",
        dimensions=[_dim("drift", "red"), _dim("queue", "amber"), _dim("cost", "green")],
    )
    assert s.alert_line() == "DEGRADED: drift"


def test_red_multiple_dims_returns_degraded_with_keys():
    s = HealthSummary(
        overall="red",
        dimensions=[_dim("drift", "red"), _dim("escalations", "red"), _dim("queue", "amber")],
    )
    assert s.alert_line() == "DEGRADED: drift, escalations"


def test_amber_single_dim_returns_watch():
    s = HealthSummary(
        overall="amber",
        dimensions=[_dim("queue", "amber"), _dim("drift", "green")],
    )
    assert s.alert_line() == "WATCH: queue"


def test_amber_multiple_dims_returns_watch_with_keys():
    s = HealthSummary(
        overall="amber",
        dimensions=[_dim("queue", "amber"), _dim("escalations", "amber"), _dim("drift", "green")],
    )
    assert s.alert_line() == "WATCH: queue, escalations"
