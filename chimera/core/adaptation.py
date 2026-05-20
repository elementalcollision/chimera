"""Failure-signature journal and auto-mutation hook (v4.5, ADR 0028).

When ACT returns ``finish_reason="max_rounds"`` AND
``missing_artifacts`` is non-empty, the agent has fragmented a
compound task into too many small calls and never reached its
deliverable. v4.5 captures that exact signature in an append-only
JSONL log; once a similar signature recurs (default ≥2), the agent
auto-emits a ``skill_proposal`` mutation so an operator can approve
a focused synthesis skill instead.

The mutation row is the *proposal*, not the activation — chimera
proposes, the operator disposes (per the canonical mutation flow).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_FILENAME = "fragmentation_log.jsonl"
_DEFAULT_THRESHOLD = 2
_PROPOSED_REASON_PREFIX = "auto-proposed: synthesis skill for fragmented compound task"


def _log_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / _DEFAULT_FILENAME


@dataclass(frozen=True)
class FragmentationRecord:
    cycle: int
    task_text: str
    rounds_used: int
    tool_call_count: int
    missing_artifacts: tuple[str, ...]
    recorded_at: str

    @classmethod
    def from_dict(cls, obj: dict) -> "FragmentationRecord":
        return cls(
            cycle=int(obj["cycle"]),
            task_text=str(obj["task_text"]),
            rounds_used=int(obj["rounds_used"]),
            tool_call_count=int(obj["tool_call_count"]),
            missing_artifacts=tuple(obj.get("missing_artifacts") or ()),
            recorded_at=str(obj["recorded_at"]),
        )

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "task_text": self.task_text,
            "rounds_used": self.rounds_used,
            "tool_call_count": self.tool_call_count,
            "missing_artifacts": list(self.missing_artifacts),
            "recorded_at": self.recorded_at,
        }


_TOKEN_SPLIT = re.compile(r"[^a-zA-Z0-9]+")


def signature(task_text: str) -> frozenset[str]:
    """Bag-of-tokens signature used to count "similar" failures.

    Filters tokens shorter than 4 chars to drop most stop-words.
    Cheap, deterministic, no NLP dependencies.
    """
    tokens = (
        t.lower() for t in _TOKEN_SPLIT.split(task_text) if len(t) >= 4
    )
    return frozenset(tokens)


def record_fragmentation(
    *,
    cycle: int,
    task_text: str,
    rounds_used: int,
    tool_call_count: int,
    missing_artifacts: list[str],
    path: Path | None = None,
) -> FragmentationRecord:
    """Append a single record to the log."""
    rec = FragmentationRecord(
        cycle=cycle,
        task_text=task_text,
        rounds_used=rounds_used,
        tool_call_count=tool_call_count,
        missing_artifacts=tuple(missing_artifacts),
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    target = path or _log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec.to_dict()) + "\n")
    return rec


def list_fragmentation(*, path: Path | None = None) -> list[FragmentationRecord]:
    target = path or _log_path()
    if not target.exists():
        return []
    out: list[FragmentationRecord] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            out.append(FragmentationRecord.from_dict(obj))
        except (KeyError, ValueError):
            continue
    return out


def count_similar(
    task_text: str,
    *,
    overlap_threshold: float = 0.5,
    path: Path | None = None,
) -> int:
    """Count past fragmentation records whose token-signature overlaps
    ``task_text`` by at least ``overlap_threshold`` (Jaccard)."""
    target_sig = signature(task_text)
    if not target_sig:
        return 0
    count = 0
    for rec in list_fragmentation(path=path):
        rec_sig = signature(rec.task_text)
        if not rec_sig:
            continue
        union = target_sig | rec_sig
        if not union:
            continue
        overlap = len(target_sig & rec_sig) / len(union)
        if overlap >= overlap_threshold:
            count += 1
    return count


def _already_proposed(
    conn: sqlite3.Connection, *, task_signature: frozenset[str]
) -> int | None:
    """If a near-identical proposal exists, return its mutation id.

    Matches by Jaccard overlap (≥0.5) on the ``signature_tokens`` payload
    field. Restricted to ``status='pending'`` so a once-rejected proposal
    can be re-emitted if the failure keeps recurring.
    """
    rows = conn.execute(
        "SELECT id, payload FROM mutations WHERE type='skill_proposal' "
        "AND status = 'pending' AND reason LIKE ?",
        (f"{_PROPOSED_REASON_PREFIX}%",),
    ).fetchall()
    for r in rows:
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except json.JSONDecodeError:
            continue
        existing_sig = frozenset(payload.get("signature_tokens") or ())
        if not existing_sig or not task_signature:
            continue
        union = task_signature | existing_sig
        if union and len(task_signature & existing_sig) / len(union) >= 0.5:
            return int(r["id"])
    return None


def maybe_propose_synthesis_skill(
    conn: sqlite3.Connection,
    *,
    cycle: int,
    task_text: str,
    missing_artifacts: list[str],
    threshold: int = _DEFAULT_THRESHOLD,
    path: Path | None = None,
) -> int | None:
    """If similar fragmentation has happened ``>= threshold`` times AND
    no proposal exists yet, emit a ``skill_proposal`` mutation.

    Returns the new mutation id, or None if no proposal was emitted.
    """
    from ..memory import bump_recurrence, create_mutation

    similar = count_similar(task_text, path=path)
    if similar < threshold:
        return None
    sig = signature(task_text)
    existing = _already_proposed(conn, task_signature=sig)
    if existing is not None:
        # v4.19: bump recurrence on the existing pending row instead of
        # enqueueing a duplicate. Returns the existing id so callers can
        # tell something happened.
        bump_recurrence(conn, existing)
        return existing
    skill_name = "synthesize_to_file"
    payload = {
        "name": skill_name,
        "description": (
            "Read a list of input files, synthesise their content into one "
            "deliverable file at the declared target path. Single read pass "
            "per source, single write at the end. No fragmentation."
        ),
        "brief": (
            "You receive `sources: list[str]` (paths to read) and `target: str` "
            "(path to write). For each source, read it ONCE. Then produce the "
            "synthesised document and write it to target in a SINGLE write. "
            "Cite each source. Do not re-read."
        ),
        "trigger_cycle": cycle,
        "trigger_task": task_text,
        "trigger_missing": list(missing_artifacts),
        "similar_count": similar,
        "signature_tokens": sorted(sig),
    }
    reason = (
        f"{_PROPOSED_REASON_PREFIX} (signature recurred {similar} time(s) "
        f"at cycle {cycle})"
    )
    mutation = create_mutation(
        conn, type="skill_proposal", payload=payload, reason=reason
    )
    return mutation.id
