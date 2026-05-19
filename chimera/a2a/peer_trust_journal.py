"""Peer-trust decision journal — append-only JSONL per peer.

Each :class:`PeerAwareDispatcher` decision (ALLOW / DEGRADE / REFUSE) appends
one record. The journal is the durable signal feeding the graph's
``TRUSTED`` edges (ADR 0017). Read-only at v3.1 — no policy reacts to it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_SUBDIR = "peer_trust_journal"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def trust_journal_dir() -> Path:
    base = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    d = Path(
        os.environ.get("CHIMERA_PEER_TRUST_JOURNAL_DIR", str(base / _DEFAULT_SUBDIR))
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    return _SAFE.sub("_", name) or "_"


def _path_for(peer: str, *, dir: Path | None = None) -> Path:
    return (dir or trust_journal_dir()) / f"{_safe(peer)}.jsonl"


@dataclass(frozen=True)
class TrustDecisionRecord:
    peer: str
    decision: str  # "ALLOW" | "DEGRADE" | "REFUSE"
    reason: str
    drift_score: float | None
    recorded_at: str


def record_decision(
    peer: str,
    decision: str,
    *,
    reason: str = "",
    drift_score: float | None = None,
    dir: Path | None = None,
) -> TrustDecisionRecord:
    rec = TrustDecisionRecord(
        peer=peer,
        decision=decision,
        reason=reason,
        drift_score=drift_score,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    path = _path_for(peer, dir=dir)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "peer": rec.peer,
                    "decision": rec.decision,
                    "reason": rec.reason,
                    "drift_score": rec.drift_score,
                    "recorded_at": rec.recorded_at,
                }
            )
            + "\n"
        )
    return rec


def list_decisions(
    peer: str | None = None, *, dir: Path | None = None
) -> list[TrustDecisionRecord]:
    d = dir or trust_journal_dir()
    if not d.exists():
        return []
    files = [_path_for(peer, dir=d)] if peer else sorted(d.glob("*.jsonl"))
    out: list[TrustDecisionRecord] = []
    for f in files:
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(
                TrustDecisionRecord(
                    peer=obj["peer"],
                    decision=obj["decision"],
                    reason=obj.get("reason", ""),
                    drift_score=obj.get("drift_score"),
                    recorded_at=obj["recorded_at"],
                )
            )
    return out


def latest_per_peer(*, dir: Path | None = None) -> dict[str, TrustDecisionRecord]:
    """Return the most recent decision for each peer."""
    out: dict[str, TrustDecisionRecord] = {}
    for r in list_decisions(dir=dir):
        prev = out.get(r.peer)
        if prev is None or r.recorded_at > prev.recorded_at:
            out[r.peer] = r
    return out
