"""Circuit breaker — CLOSED / OPEN / HALF_OPEN state machine.

Ported from village's clerk-client circuit-breaker pattern per
pillar-positioning.md Pattern 5.

Usage:

.. code-block:: python

    breaker = CircuitBreaker(name="openrouter")
    if not breaker.can_call():
        raise CircuitOpen(...)
    try:
        result = await provider.complete(...)
    except SomeError:
        breaker.record_failure()
        raise
    else:
        breaker.record_success()

The breaker has no async machinery of its own — the caller decides when
to ``can_call()`` / ``record_*``. This keeps it testable as pure logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpen(Exception):
    """Raised when callers explicitly want exceptions on fast-fail."""


@dataclass
class CircuitBreaker:
    """Tracks failures, fast-fails when OPEN, probes on recovery."""

    name: str
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    half_open_max_probes: int = 3

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open_probes: int = 0
    fast_fails_total: int = 0

    def can_call(self, *, now: float | None = None) -> bool:
        ts = now if now is not None else time.monotonic()
        if self.state is CircuitState.CLOSED:
            return True
        if self.state is CircuitState.OPEN:
            assert self.opened_at is not None
            if ts - self.opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self.half_open_probes = 0
                return self._allow_half_open_probe()
            self.fast_fails_total += 1
            return False
        # HALF_OPEN
        return self._allow_half_open_probe()

    def _allow_half_open_probe(self) -> bool:
        if self.half_open_probes < self.half_open_max_probes:
            self.half_open_probes += 1
            return True
        return False

    def record_success(self) -> None:
        if self.state is CircuitState.HALF_OPEN:
            # Reset to CLOSED only after enough successful probes.
            if self.half_open_probes >= self.half_open_max_probes:
                self._reset()
            else:
                # Mid-recovery success — count it; failure during HALF_OPEN
                # still trips back to OPEN.
                self.consecutive_failures = 0
        else:
            self._reset()

    def record_failure(self, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        self.consecutive_failures += 1
        if self.state is CircuitState.HALF_OPEN:
            # Single failure during recovery → straight back to OPEN.
            self._open(ts)
            return
        if self.consecutive_failures >= self.failure_threshold:
            self._open(ts)

    def _open(self, ts: float) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = ts
        self.half_open_probes = 0

    def _reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = None
        self.half_open_probes = 0

    # ── introspection (for /health endpoints, observability) ──────

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "opened_at": self.opened_at,
            "fast_fails_total": self.fast_fails_total,
        }
