"""Tests for positioning primitives (drain, sensor, circuit breaker)."""

from __future__ import annotations

import asyncio
import signal as _signal

import pytest

from chimera.positioning import (
    CircuitBreaker,
    CircuitState,
    PositionReading,
    drain_and_wait,
    install_drain_handlers,
    read_position,
)


# ── drain ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_handlers_install_without_error():
    event = asyncio.Event()
    install_drain_handlers(event, service_name="test")
    # Calling twice is idempotent.
    install_drain_handlers(event, service_name="test")
    assert not event.is_set()


@pytest.mark.asyncio
async def test_drain_handlers_fire_on_sigint():
    """Send SIGINT to ourselves; the event should set."""
    event = asyncio.Event()
    install_drain_handlers(event, signals=(_signal.SIGUSR1,))
    # Use SIGUSR1 because pytest already hijacks SIGINT.
    import os
    os.kill(os.getpid(), _signal.SIGUSR1)
    drained = await drain_and_wait(event, timeout=1.0)
    assert drained is True
    assert event.is_set()


@pytest.mark.asyncio
async def test_drain_and_wait_times_out():
    event = asyncio.Event()
    drained = await drain_and_wait(event, timeout=0.05)
    assert drained is False


# ── sensor ──────────────────────────────────────────────────


def test_read_position_returns_a_reading():
    r = read_position()
    assert isinstance(r, PositionReading)
    # Whatever the OS gives us, render must not crash.
    assert "load1=" in r.render()


def test_position_under_pressure_false_for_low_usage():
    r = PositionReading(
        cpu_load_1min=0.5,
        memory_used_pct=0.20,
        state_disk_used_pct=0.10,
        mind_disk_used_pct=0.05,
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert r.under_pressure() is False


def test_position_under_pressure_true_for_high_mem():
    r = PositionReading(
        cpu_load_1min=0.5,
        memory_used_pct=0.95,
        state_disk_used_pct=0.10,
        mind_disk_used_pct=0.05,
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert r.under_pressure() is True


def test_position_under_pressure_true_for_full_disk():
    r = PositionReading(
        cpu_load_1min=0.5,
        memory_used_pct=0.20,
        state_disk_used_pct=0.99,
        mind_disk_used_pct=0.05,
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert r.under_pressure() is True


# ── circuit breaker ─────────────────────────────────────────


def test_circuit_starts_closed_and_allows_calls():
    cb = CircuitBreaker(name="x")
    assert cb.state is CircuitState.CLOSED
    assert cb.can_call() is True


def test_circuit_opens_after_threshold_failures():
    cb = CircuitBreaker(name="x", failure_threshold=3)
    cb.record_failure(now=0.0)
    cb.record_failure(now=1.0)
    assert cb.state is CircuitState.CLOSED
    cb.record_failure(now=2.0)
    assert cb.state is CircuitState.OPEN


def test_circuit_fast_fails_while_open():
    cb = CircuitBreaker(name="x", failure_threshold=1, cooldown_seconds=10)
    cb.record_failure(now=0.0)
    assert cb.state is CircuitState.OPEN
    assert cb.can_call(now=1.0) is False
    assert cb.fast_fails_total == 1
    assert cb.can_call(now=2.0) is False
    assert cb.fast_fails_total == 2


def test_circuit_transitions_to_half_open_after_cooldown():
    cb = CircuitBreaker(
        name="x", failure_threshold=1, cooldown_seconds=10, half_open_max_probes=2
    )
    cb.record_failure(now=0.0)
    assert cb.state is CircuitState.OPEN
    # After cooldown, first can_call() flips to HALF_OPEN and consumes a probe.
    assert cb.can_call(now=11.0) is True
    assert cb.state is CircuitState.HALF_OPEN
    # Second probe allowed.
    assert cb.can_call(now=11.5) is True
    # Third probe blocked.
    assert cb.can_call(now=11.6) is False


def test_circuit_failure_in_half_open_reopens():
    cb = CircuitBreaker(name="x", failure_threshold=1, cooldown_seconds=10)
    cb.record_failure(now=0.0)
    cb.can_call(now=11.0)  # → HALF_OPEN
    cb.record_failure(now=11.5)
    assert cb.state is CircuitState.OPEN


def test_circuit_success_in_half_open_after_probes_closes():
    cb = CircuitBreaker(
        name="x", failure_threshold=1, cooldown_seconds=10, half_open_max_probes=2
    )
    cb.record_failure(now=0.0)
    cb.can_call(now=11.0)  # probe 1
    cb.can_call(now=11.5)  # probe 2
    cb.record_success()
    assert cb.state is CircuitState.CLOSED


def test_circuit_snapshot_for_health_endpoint():
    cb = CircuitBreaker(name="provider-x")
    snap = cb.snapshot()
    assert snap["name"] == "provider-x"
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0
