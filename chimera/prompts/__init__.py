"""Prompt construction — voice, hardware probe, history formatting."""

from __future__ import annotations

import os
import sqlite3

from .hardware import HardwareSummary, probe as probe_hardware
from .history import HistoryStats, recent_history
from .voice import CHIMERA_VOICE, base_voice, foreign_task_guidance, foreign_voice


def _foreign_repo() -> str:
    """The foreign target repo for a multi-repo soak (ADR 0186 B.3), or ""."""
    return os.environ.get("CHIMERA_FOREIGN_REPO", "").strip()


def build_system_prompt(
    db: sqlite3.Connection,
    *,
    cycle: int,
    last_n_cycles: int = 3,
    extra: str | None = None,
) -> str:
    """Assemble the full system prompt: voice + hardware + history (+ extra).

    In a FOREIGN-repo soak (``CHIMERA_FOREIGN_REPO`` set, ADR 0186 B.3) the
    chimera self-identity voice and the caller's chimera-specific ``extra``
    (``DEFAULT_SYSTEM_PROMPT_EXTRA`` names chimera/ paths) are wrong context, so
    a neutral repo-framed voice + task guidance are substituted. With the env
    unset the behaviour is byte-identical to before.
    """
    repo = _foreign_repo()
    parts = [foreign_voice(repo) if repo else base_voice()]
    parts.append("\n---")
    parts.append(probe_hardware().render())
    parts.append(recent_history(db, current_cycle=cycle, last_n_cycles=last_n_cycles).render())
    # Foreign mode replaces the chimera-specific extra with neutral guidance;
    # self mode keeps the caller-supplied extra verbatim.
    foreign_extra = foreign_task_guidance(repo) if repo else None
    effective_extra = foreign_extra if repo else extra
    if effective_extra:
        parts.append("")
        parts.append(effective_extra)
    return "\n".join(parts)


__all__ = [
    "CHIMERA_VOICE",
    "HardwareSummary",
    "HistoryStats",
    "base_voice",
    "build_system_prompt",
    "foreign_task_guidance",
    "foreign_voice",
    "probe_hardware",
    "recent_history",
]
