"""Daily engine scheduler — time-of-day routing + per-day idempotency.

One engine runs per cycle at most. Windows (UTC, configurable via env):

  - 08:00–13:59 → Discovery
  - 14:00–21:59 → Curiosity
  - 22:00–07:59 → Reflection (wraps midnight)

A given engine fires at most ONCE per UTC day. Per-day state persists in
``state/engines/last_runs.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Literal

EngineName = Literal["discovery", "curiosity", "reflection"]


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _engine_individually_enabled(name: EngineName) -> bool:
    """v4.72 (ADR 0091, P5): selective per-engine enable.

    Default ON; an operator opts out of a specific engine with
    e.g. ``CHIMERA_DISCOVERY_ENABLED=0``. Useful when one engine is
    producing low-value chronicle entries while the other two are
    pulling their weight (the post-mortem's typical failure mode).
    """
    key = f"CHIMERA_{name.upper()}_ENABLED"
    return os.environ.get(key, "1") not in ("0", "false", "False")


def engine_enable_snapshot() -> dict[str, bool]:
    """Operator-facing view of which engines are currently enabled."""
    return {
        "discovery": _engine_individually_enabled("discovery"),
        "curiosity": _engine_individually_enabled("curiosity"),
        "reflection": _engine_individually_enabled("reflection"),
    }


class EngineScheduler:
    """Persists per-engine last-fire dates and decides what's due."""

    def __init__(
        self,
        state_path: Path,
        *,
        discovery_hour: int | None = None,
        curiosity_hour: int | None = None,
        reflection_hour: int | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.discovery_hour = int(
            discovery_hour if discovery_hour is not None
            else os.environ.get("CHIMERA_DISCOVERY_HOUR", "8")
        )
        self.curiosity_hour = int(
            curiosity_hour if curiosity_hour is not None
            else os.environ.get("CHIMERA_CURIOSITY_HOUR", "14")
        )
        self.reflection_hour = int(
            reflection_hour if reflection_hour is not None
            else os.environ.get("CHIMERA_REFLECTION_HOUR", "22")
        )
        self._last_runs: dict[str, str] = self._load()

    # ── state I/O ──────────────────────────────────────

    def _load(self) -> dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._last_runs, sort_keys=True, indent=2))

    # ── decisions ──────────────────────────────────────

    def pick_due(
        self,
        *,
        now: dt.datetime | None = None,
        force: EngineName | None = None,
    ) -> EngineName | None:
        """Return which engine (if any) is due to run.

        - ``force`` bypasses both the time window AND the per-day gate.
        - Otherwise: pick the engine whose UTC window contains ``now`` AND
          which hasn't fired yet today.
        - Reflection's window wraps midnight; "today" is anchored at UTC.
        """
        ts = now or _utc_now()
        if force:
            return force
        # Global kill switch — `CHIMERA_ENGINES_ENABLED=0` makes every
        # cycle skip the PLAN engine entirely. Useful for ad-hoc manual
        # cycles where the 60-90s engine cost is unwanted.
        if os.environ.get("CHIMERA_ENGINES_ENABLED", "1") == "0":
            return None
        today = ts.strftime("%Y-%m-%d")
        hour = ts.hour
        candidate: EngineName | None = None
        if self._window_contains(hour, self.discovery_hour, self.curiosity_hour):
            candidate = "discovery"
        elif self._window_contains(hour, self.curiosity_hour, self.reflection_hour):
            candidate = "curiosity"
        else:
            candidate = "reflection"
        # v4.72 (ADR 0091, P5): selective per-engine enable. The
        # global switch above stays as a coarse kill; this is granular.
        # Default ON for each — opt-out by setting `CHIMERA_<NAME>_ENABLED=0`.
        if not _engine_individually_enabled(candidate):
            return None
        if self._last_runs.get(candidate) == today:
            return None
        return candidate

    @staticmethod
    def _window_contains(hour: int, start: int, end: int) -> bool:
        """Inclusive-of-start, exclusive-of-end; handles wrap (start > end)."""
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def mark_ran(self, engine: EngineName, *, now: dt.datetime | None = None) -> None:
        ts = now or _utc_now()
        self._last_runs[engine] = ts.strftime("%Y-%m-%d")
        self._save()

    def snapshot(self) -> dict[str, str]:
        return dict(self._last_runs)
