"""Skill-assembly attempt journal (v4.9).

Persists every ``LadderResult`` from ``chimera skills assemble`` to
``state/skill_assembly_log.jsonl``. The dashboard reads this to show
per-mutation, per-tier, per-witness telemetry beyond the single
``mutation.reason`` string.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ladder import LadderResult


_DEFAULT_FILENAME = "skill_assembly_log.jsonl"


def _log_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / _DEFAULT_FILENAME


@dataclass(frozen=True)
class AssemblyJournalEntry:
    mutation_id: int
    skill_name: str
    winning_tier: str | None
    final_score: float
    final_ok: bool
    attempts: list[dict]
    recorded_at: str


def record_assembly(
    mutation_id: int,
    skill_name: str,
    result: LadderResult,
    *,
    path: Path | None = None,
) -> AssemblyJournalEntry:
    """Append one ladder run to the assembly log."""
    entry = AssemblyJournalEntry(
        mutation_id=mutation_id,
        skill_name=skill_name,
        winning_tier=result.winning_tier,
        final_score=result.validation.score if result.validation else 0.0,
        final_ok=result.validation.ok if result.validation else False,
        attempts=[
            {
                "tier": a.tier,
                "assembled_ok": a.assembled_ok,
                "validation_score": a.validation_score,
                "validation_ok": a.validation_ok,
                "failure_reason": a.failure_reason,
                "revised": a.revised,
                "revised_score": a.revised_score,
                "witnesses": list(a.witnesses),
                "winning_witness": a.winning_witness,
            }
            for a in result.attempts
        ],
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    target = path or _log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")
    return entry


def list_assemblies(
    *, path: Path | None = None, limit: int | None = None,
) -> list[dict]:
    """Read raw journal entries (newest last)."""
    target = path or _log_path()
    if not target.exists():
        return []
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit is not None:
        rows = rows[-limit:]
    return rows
