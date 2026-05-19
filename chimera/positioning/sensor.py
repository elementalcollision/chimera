"""Dynamic positional sensor — load, memory pressure, disk pressure.

Complements :mod:`chimera.prompts.hardware` (which probes static specs).
This module reports runtime *state* the agent uses to decide how to
position itself (e.g. back off heavy tasks when memory is tight).
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PositionReading:
    cpu_load_1min: float | None
    memory_used_pct: float | None
    state_disk_used_pct: float | None
    mind_disk_used_pct: float | None
    timestamp: str

    def render(self) -> str:
        def _pct(v: float | None) -> str:
            return f"{v:.0%}" if v is not None else "?"
        return (
            f"load1={self.cpu_load_1min if self.cpu_load_1min is not None else '?'} "
            f"mem={_pct(self.memory_used_pct)} "
            f"disk[state]={_pct(self.state_disk_used_pct)} "
            f"disk[mind]={_pct(self.mind_disk_used_pct)}"
        )

    def under_pressure(
        self,
        *,
        mem_threshold: float = 0.90,
        disk_threshold: float = 0.95,
    ) -> bool:
        """Coarse 'should we back off?' signal."""
        if self.memory_used_pct is not None and self.memory_used_pct >= mem_threshold:
            return True
        for d in (self.state_disk_used_pct, self.mind_disk_used_pct):
            if d is not None and d >= disk_threshold:
                return True
        return False


def _loadavg_1min() -> float | None:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def _memory_used_pct() -> float | None:
    """Best-effort 'how much memory is used vs available?'."""
    try:
        with open("/proc/meminfo") as f:
            data = {}
            for line in f:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    data[key.strip()] = int(parts[0])
        total = data.get("MemTotal")
        available = data.get("MemAvailable")
        if total and available is not None:
            return max(0.0, min(1.0, (total - available) / total))
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return None


def _disk_used_pct(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(str(path))
        if usage.total <= 0:
            return None
        return (usage.total - usage.free) / usage.total
    except (FileNotFoundError, PermissionError, OSError):
        return None


def read_position() -> PositionReading:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    mind_dir = Path(os.environ.get("CHIMERA_MIND_DIR", "mind"))
    return PositionReading(
        cpu_load_1min=_loadavg_1min(),
        memory_used_pct=_memory_used_pct(),
        state_disk_used_pct=_disk_used_pct(state_dir),
        mind_disk_used_pct=_disk_used_pct(mind_dir),
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    )
