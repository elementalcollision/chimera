"""v4.65 (ADR 0084) — auto-loop integration for the task splitter.

ADR 0082 shipped the splitter as an operator-manual surface. This
module promotes it to default-off ASSESS-phase auto-invocation:

  * gate ``CHIMERA_TASK_SPLITTER_ENABLED=1`` (default OFF)
  * detect: heuristic confidence ≥ 0.5 AND ≥ N prior failures on a
    signature that overlaps the task's signature ≥ 50% AND no
    pending ``task_split`` mutation for this signature already
  * propose: call ``split_task`` (sonnet-tier, ~$0.003) and enqueue
    a ``type="task_split"`` mutation with the proposed sub-tasks
  * operator approves via ``chimera mutations approve <id>``
  * operator applies via ``chimera mutations apply <id>``, which
    rewrites ``mind/INBOX.md`` (marks the original ``[-]``, appends
    the sub-tasks as new ``[ ]`` lines)

Cost guard: detection is heuristic-only (free). Only when the
heuristic AND escalation memory agree does the splitter call fire.
With ``min_failures=3``, a typical session sees zero auto-invocations
on healthy INBOXes and at most a small handful on stuck ones.

Why a mutation instead of auto-rewriting INBOX? Because rewriting
operator-owned files without consent is a bigger trust step than a
heuristic is worth. The agent proposes; the operator applies. Same
pattern as the v4.39 ``kill_entity`` workflow.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from .escalation import _signature
from .task_splitter import is_splittable_shape

logger = logging.getLogger(__name__)


def task_split_enabled() -> bool:
    """Default OFF. Opt in with ``CHIMERA_TASK_SPLITTER_ENABLED=1``."""
    return os.environ.get(
        "CHIMERA_TASK_SPLITTER_ENABLED", ""
    ).lower() in ("1", "true", "yes")


def _proposed_signatures(conn: sqlite3.Connection) -> set[str]:
    """Signatures that already have a pending or approved task_split
    mutation. Used to avoid re-proposing the same split every cycle."""
    from ..memory.mutations import list_mutations
    out: set[str] = set()
    for status in ("pending", "approved"):
        for m in list_mutations(conn, type="task_split", status=status):
            if isinstance(m.payload, dict):
                sig = m.payload.get("signature")
                if isinstance(sig, str):
                    out.add(sig)
    return out


def _count_prior_failures_for_signature(
    conn: sqlite3.Connection, signature: str, *, overlap_threshold: float = 0.5,
) -> int:
    """Number of task_escalations rows with signature overlap ≥ threshold."""
    if not signature:
        return 0
    incoming = set(signature.split(","))
    if not incoming:
        return 0
    try:
        rows = conn.execute(
            "SELECT signature FROM task_escalations"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for r in rows:
        existing = set((r["signature"] or "").split(","))
        if not existing:
            continue
        union = incoming | existing
        if not union:
            continue
        overlap = len(incoming & existing) / len(union)
        if overlap >= overlap_threshold:
            n += 1
    return n


def should_propose_split_for(
    conn: sqlite3.Connection,
    task_text: str,
    *,
    min_failures: int = 3,
    min_confidence: float = 0.5,
) -> bool:
    """Combined predicate: heuristic + escalation memory + dedup.

    Returns True iff:
      1. ``is_splittable_shape`` reports confidence ≥ ``min_confidence``, AND
      2. ``task_escalations`` has ≥ ``min_failures`` overlapping rows
         (the v4.54 hot-signature definition, plus one — gives the
         agent two chances on the bundled shape before splitting), AND
      3. no pending or approved ``task_split`` mutation already
         targets this signature.
    """
    sig = _signature(task_text)
    if not sig:
        return False
    signal = is_splittable_shape(task_text)
    if signal.confidence < min_confidence:
        return False
    if _count_prior_failures_for_signature(conn, sig) < min_failures:
        return False
    if sig in _proposed_signatures(conn):
        return False
    return True


def propose_task_split(
    conn: sqlite3.Connection,
    task_text: str,
    subtasks: list[str],
) -> int | None:
    """Enqueue a ``task_split`` mutation. Returns the mutation id, or
    None if ``subtasks`` is empty (nothing actionable to propose).
    """
    if not subtasks:
        return None
    from ..memory.mutations import create_mutation
    sig = _signature(task_text)
    payload = {
        "signature": sig,
        "original_task": task_text,
        "subtasks": subtasks,
    }
    reason = (
        f"task splitter (v4.65): heuristic + ≥3 prior failures on this "
        f"signature; proposing {len(subtasks)} sub-task(s)"
    )
    m = create_mutation(conn, type="task_split", payload=payload, reason=reason)
    conn.commit()
    return m.id


def _find_task_line(lines: list[str], task_text: str) -> int | None:
    """Locate the ``- [ ] <task_text>`` line in INBOX. Tolerant of
    leading whitespace and the exact text match. Returns None when
    the task can't be found — caller decides what to do."""
    needle = task_text.strip()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("- ["):
            continue
        # Lines look like ``- [ ] body`` or ``- [x] body``.
        # Extract body after the checkbox.
        try:
            body = stripped.split("]", 1)[1].lstrip()
        except IndexError:
            continue
        # Tolerant match: needle is a prefix or full match (INBOX may
        # have wrapped or trailing markers).
        if body == needle or body.startswith(needle[:200]):
            return i
    return None


def apply_task_split(
    conn: sqlite3.Connection,
    mutation_id: int,
    inbox_path: Path,
) -> dict[str, object]:
    """Apply an approved ``task_split`` mutation: mark the original
    task ``[-]`` in INBOX and append the sub-tasks as ``[ ]`` lines.

    Returns ``{"ok": bool, "reason": str, ...}`` for the CLI handler.
    Idempotent — if the mutation is already applied, no-op + log.
    """
    from ..memory.mutations import (
        get_mutation, mark_applied, mark_failed,
    )

    m = get_mutation(conn, mutation_id)
    if m is None:
        return {"ok": False, "reason": f"mutation #{mutation_id} not found"}
    if m.type != "task_split":
        return {
            "ok": False,
            "reason": f"mutation #{mutation_id} is type={m.type!r}, expected task_split",
        }
    if m.status == "applied":
        return {"ok": True, "reason": "already applied (no-op)"}
    if m.status != "approved":
        return {
            "ok": False,
            "reason": f"mutation #{mutation_id} is status={m.status!r}, "
                      "must be approved before apply",
        }
    payload = m.payload if isinstance(m.payload, dict) else {}
    original = payload.get("original_task")
    subtasks = payload.get("subtasks")
    if not isinstance(original, str) or not original.strip():
        mark_failed(conn, mutation_id, reason="payload missing original_task")
        return {"ok": False, "reason": "payload missing original_task"}
    if not isinstance(subtasks, list) or not subtasks:
        mark_failed(conn, mutation_id, reason="payload missing subtasks")
        return {"ok": False, "reason": "payload missing subtasks"}

    if not inbox_path.exists():
        mark_failed(conn, mutation_id, reason=f"INBOX missing: {inbox_path}")
        return {"ok": False, "reason": f"INBOX missing: {inbox_path}"}

    text = inbox_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = _find_task_line(lines, original)
    if idx is None:
        mark_failed(
            conn, mutation_id,
            reason="original task not found in INBOX (may have been edited)",
        )
        return {"ok": False, "reason": "original task line not found in INBOX"}

    # Mark the original line `[-]` with an annotation, preserving
    # leading whitespace so list indentation survives.
    orig_line = lines[idx]
    leading = orig_line[: len(orig_line) - len(orig_line.lstrip())]
    annotated = (
        f"{leading}- [-] {original.strip()} "
        f"[SPLIT v4.65: mutation #{mutation_id} → see {len(subtasks)} sub-tasks below]"
    )
    new_lines = list(lines)
    new_lines[idx] = annotated
    # Insert sub-tasks immediately after the original line. Each
    # becomes a new `- [ ]` item at the same indent level.
    inserted: list[str] = []
    for sub in subtasks:
        sub_clean = " ".join(sub.split())  # collapse whitespace
        inserted.append(f"{leading}- [ ] {sub_clean}")
    for i, new_line in enumerate(inserted, start=1):
        new_lines.insert(idx + i, new_line)

    inbox_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    mark_applied(conn, mutation_id, reason=f"split into {len(subtasks)} sub-task(s)")
    return {
        "ok": True,
        "reason": f"split into {len(subtasks)} sub-task(s)",
        "original_line_index": idx,
        "inserted": len(inserted),
    }


__all__ = [
    "task_split_enabled",
    "should_propose_split_for",
    "propose_task_split",
    "apply_task_split",
]
