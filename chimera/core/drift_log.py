"""Append-only drift composite journal (v4.15, ADR 0037).

Each FLUSH-phase composite reading appends one JSONL row to
``state/drift_log.jsonl``. The dashboard's sparkline widget renders
the last N rows so trend is visible (not just the single last value
that lives in HEARTBEAT.md).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


_DEFAULT_FILENAME = "drift_log.jsonl"


def _log_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / _DEFAULT_FILENAME


@dataclass(frozen=True)
class DriftLogRecord:
    cycle: int
    composite_score: float
    severity: str
    action: str
    reason: str
    recorded_at: str


def record_drift(
    *,
    cycle: int,
    composite_score: float,
    severity: str,
    action: str,
    reason: str,
    path: Path | None = None,
) -> DriftLogRecord:
    rec = DriftLogRecord(
        cycle=cycle,
        composite_score=composite_score,
        severity=severity,
        action=action,
        reason=reason,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    target = path or _log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "cycle": rec.cycle,
                    "composite_score": rec.composite_score,
                    "severity": rec.severity,
                    "action": rec.action,
                    "reason": rec.reason,
                    "recorded_at": rec.recorded_at,
                }
            )
            + "\n"
        )
    return rec


def list_drift(*, path: Path | None = None, limit: int | None = None) -> list[DriftLogRecord]:
    target = path or _log_path()
    if not target.exists():
        return []
    out: list[DriftLogRecord] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out.append(
                DriftLogRecord(
                    cycle=int(obj["cycle"]),
                    composite_score=float(obj["composite_score"]),
                    severity=str(obj["severity"]),
                    action=str(obj["action"]),
                    reason=str(obj["reason"]),
                    recorded_at=str(obj["recorded_at"]),
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    if limit is not None:
        out = out[-limit:]
    return out
