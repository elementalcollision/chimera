"""Self-origination precision log (thrust ② chip 3, ADR 0161).

Self-scan (chips 1–2) proposes maintenance tasks; this records which proposals a
human accepts, rejects, or runs — the labelled dataset that measures origination
PRECISION (the fraction of proposals worth acting on). That number, together with
critic calibration, is what eventually earns an opt-in auto-run; until then the
loop stays proposal-only and a human supplies the labels.

Append-only JSONL: each line is a ``proposal`` or a ``decision`` event keyed by a
deterministic ``proposal_id`` (a content hash, so re-emitting the same candidate
is idempotent). ``precision_report`` folds the log — latest decision per proposal
wins — into accepted / rejected / undecided counts and a precision number.

Charter: never raise on a malformed line (skip it); timestamps are injected so
the module is deterministic under test.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_DECISIONS = {"accepted", "rejected", "ran"}


def proposal_id(goal: str, files: list[str], ts: str) -> str:
    """Deterministic short id from the candidate's content + timestamp."""
    raw = goal + "|" + ",".join(files) + "|" + ts
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]  # noqa: S324


@dataclass
class PrecisionReport:
    proposed: int = 0
    accepted: int = 0
    rejected: int = 0
    ran: int = 0
    undecided: int = 0

    @property
    def decided(self) -> int:
        return self.accepted + self.rejected

    @property
    def precision(self) -> float:
        """accepted / (accepted + rejected) — share of *decided* proposals a
        human judged worth acting on. ``ran`` is an accept that also executed."""
        denom = self.accepted + self.rejected
        return self.accepted / denom if denom else 0.0

    def summary(self) -> str:
        if not self.proposed:
            return "self-scan precision: no proposals logged yet"
        prec = (f"{self.precision:.0%}" if self.decided else "n/a (none decided)")
        return (
            f"self-scan precision: {self.precision_line()}\n"
            f"  proposed {self.proposed} | accepted {self.accepted} "
            f"(ran {self.ran}) | rejected {self.rejected} | "
            f"undecided {self.undecided} | precision {prec}"
        )

    def precision_line(self) -> str:
        if not self.decided:
            return "no decisions yet — precision unmeasured"
        return f"{self.accepted}/{self.decided} accepted"


def default_log_path() -> Path:
    """state/self_scan_proposals.jsonl under CHIMERA_STATE_DIR or cwd/state."""
    import os

    base = os.environ.get("CHIMERA_STATE_DIR") or "state"
    return Path(base) / "self_scan_proposals.jsonl"


def _append(path: Path | str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def log_proposal(
    goal: str, files: list[str], source: str, score: float, *,
    path: Path | str, ts: str,
) -> str:
    """Append a ``proposal`` event; returns its (deterministic) id. Idempotent in
    intent — re-emitting the same candidate yields the same id (the report folds
    duplicates by id)."""
    pid = proposal_id(goal, files, ts)
    _append(path, {
        "type": "proposal", "id": pid, "ts": ts, "goal": goal,
        "files": files, "source": source, "score": score,
    })
    return pid


def record_decision(
    proposal_id_: str, decision: str, *, path: Path | str, ts: str,
) -> None:
    """Append a ``decision`` event (accepted / rejected / ran) for a proposal."""
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_DECISIONS)}")
    _append(path, {
        "type": "decision", "id": proposal_id_, "ts": ts, "decision": decision,
    })


def _read(path: Path | str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue  # skip malformed line, never raise
    return rows


def precision_report(path: Path | str) -> PrecisionReport:
    """Fold the append-only log into a precision report. The LATEST decision per
    proposal wins (a reject can be revised to accept, etc.)."""
    rows = _read(path)
    proposals: set[str] = set()
    latest: dict[str, str] = {}   # id -> latest decision
    for r in rows:
        rid = r.get("id")
        if not rid:
            continue
        if r.get("type") == "proposal":
            proposals.add(rid)
        elif r.get("type") == "decision" and r.get("decision") in _DECISIONS:
            latest[rid] = r["decision"]
    rep = PrecisionReport(proposed=len(proposals))
    for pid in proposals:
        d = latest.get(pid)
        if d == "rejected":
            rep.rejected += 1
        elif d in ("accepted", "ran"):
            rep.accepted += 1
            if d == "ran":
                rep.ran += 1
        else:
            rep.undecided += 1
    return rep
