"""Prompt construction — voice, hardware probe, history formatting."""

from __future__ import annotations

import sqlite3

from .hardware import HardwareSummary, probe as probe_hardware
from .history import HistoryStats, recent_history
from .voice import CHIMERA_VOICE, base_voice


def build_system_prompt(
    db: sqlite3.Connection,
    *,
    cycle: int,
    last_n_cycles: int = 3,
    extra: str | None = None,
) -> str:
    """Assemble the full system prompt: voice + hardware + history (+ extra)."""
    parts = [base_voice()]
    parts.append("\n---")
    parts.append(probe_hardware().render())
    parts.append(recent_history(db, current_cycle=cycle, last_n_cycles=last_n_cycles).render())
    if extra:
        parts.append("")
        parts.append(extra)
    return "\n".join(parts)


__all__ = [
    "CHIMERA_VOICE",
    "HardwareSummary",
    "HistoryStats",
    "base_voice",
    "build_system_prompt",
    "probe_hardware",
    "recent_history",
]
