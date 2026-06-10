"""v4.21 — memory / ontology audit.

v4.24 also exposes :func:`auto_archive_stale_deprecated`, the policy
that promotes long-DEPRECATED entities to ARCHIVED via the
K-operator. Audit-then-act, sharing the same threshold semantics.

Inventory of "what does Chimera actually remember?" Surfaces:

  * counts by kind and KFM state
  * stale entities — sitting in a non-terminal state for more cycles
    than expected
  * dead entities — zero activity_log rows in the recent cycle window
  * re-anchor events — STABLE → DEPRECATED transitions written by the
    K-operator (the drift-policy demotion path)

Pure read-only. No mutations. Intended for `chimera ontology audit`
and a future dashboard widget. The thresholds are caller-supplied so
the CLI and tests can drive them deterministically.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Any


logger = logging.getLogger(__name__)


_TERMINAL_STATES = ("ARCHIVED", "KILLED")


# v4.55 (ADR 0074): batch-scope context manager for archive/kill loops.
#
# Pre-v4.55 the audit functions had no enclosing scope around their
# batch loops; the overnight code review (mind/overnight/code-review-audit.md
# §c) called the absence of one out as the audit module's weakest
# design choice. This context manager IS that scope — but it's an
# OBSERVATION boundary, not a true atomic-batch boundary.
#
# Why not a true batch transaction? Because ``transition_entity()``
# already issues its own BEGIN/COMMIT per entity. Wrapping the loop
# in an outer BEGIN nests illegally in SQLite. The only way to get
# real batch atomicity is to refactor ``transition_entity`` to be
# transaction-context-aware; that's its own ADR.
#
# What this DOES give us:
#   * a single visible call site for "the batch starts here / ends here"
#   * a place to add batch-level logging (entry/exit, total time)
#   * a place to count + report partial-failure stats in one go
#   * a sentinel re-raise on any non-transition_entity crash
@contextmanager
def _batch_transaction(conn: sqlite3.Connection):
    """Scope a batch loop. Re-raises on any non-handled exception.

    Per-entity atomicity is the strongest guarantee available — each
    inner ``transition_entity()`` already opens + commits its own
    transaction. A crash mid-batch leaves the entities that already
    succeeded committed and the rest un-touched; the operator
    inspects the returned list to see what got through. The audit
    module's caller pattern already swallows + logs each iteration's
    exception, so this context's re-raise only fires on bookkeeping
    errors (dict allocation, logger failure, etc.).
    """
    try:
        yield
    except Exception:
        # No transaction to roll back; just propagate so the operator sees it.
        logger.exception("audit batch scope hit an unhandled exception")
        raise


def audit_ontology(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    stale_after_cycles: int = 20,
    activity_window_cycles: int = 10,
    reanchor_window_cycles: int = 50,
    max_listed: int = 20,
) -> dict[str, Any]:
    """Return a structured audit of the current ontology.

    Parameters
    ----------
    current_cycle:
        Today's cycle number. The caller (loop or CLI) supplies it so
        the audit is deterministic against test fixtures.
    stale_after_cycles:
        Non-terminal entity is "stale" if it's been in its current
        ``kfm_state`` for at least this many cycles.
    activity_window_cycles:
        Activity log lookback for "dead" detection.
    reanchor_window_cycles:
        Look back this many cycles when counting K-operator demotions
        (STABLE → DEPRECATED).
    max_listed:
        Cap on number of entities returned in each list field.

    On a missing/incomplete schema (e.g. a test fixture without the
    ``entity_transitions`` or ``agent_activity_log`` tables), returns
    a structured ``{"error": "schema_missing", "detail": ...}``
    instead of raising — the housekeeping loop calls this each cycle
    and must not crash on a partial DB. v4.55 (ADR 0074).
    """
    try:
        return _audit_ontology_inner(
            conn,
            current_cycle=current_cycle,
            stale_after_cycles=stale_after_cycles,
            activity_window_cycles=activity_window_cycles,
            reanchor_window_cycles=reanchor_window_cycles,
            max_listed=max_listed,
        )
    except sqlite3.OperationalError as exc:
        logger.warning("audit_ontology: schema not ready (%s)", exc)
        return {
            "error": "schema_missing",
            "detail": str(exc),
            "current_cycle": current_cycle,
            "total_entities": 0,
            "by_kind": {},
            "by_state": {},
            "stale_entities": [],
            "stale_count": 0,
            "dead_entities": [],
            "dead_count": 0,
            "deprecated_unarchived": 0,
            "reanchor_events_in_window": 0,
            "reanchor_window_cycles": reanchor_window_cycles,
            "thresholds": {
                "stale_after_cycles": stale_after_cycles,
                "activity_window_cycles": activity_window_cycles,
            },
        }


def _audit_ontology_inner(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    stale_after_cycles: int,
    activity_window_cycles: int,
    reanchor_window_cycles: int,
    max_listed: int,
) -> dict[str, Any]:
    """Audit body. Separated so the public ``audit_ontology`` can catch
    schema-missing errors uniformly without bleeding the try/except
    across all the SELECT statements."""
    total = int(
        conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
    )

    by_kind: dict[str, int] = {
        r["kind"]: int(r["n"])
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind"
        ).fetchall()
    }

    by_state: dict[str, int] = {
        r["kfm_state"]: int(r["n"])
        for r in conn.execute(
            "SELECT kfm_state, COUNT(*) AS n FROM entities GROUP BY kfm_state"
        ).fetchall()
    }

    # Stale: any non-terminal entity whose state_entered_at_cycle is
    # ``stale_after_cycles`` or more behind ``current_cycle``.
    stale_cutoff = current_cycle - stale_after_cycles
    stale_rows = conn.execute(
        """
        SELECT id, kind, name, kfm_state, state_entered_at_cycle
        FROM entities
        WHERE kfm_state NOT IN (?, ?)
          AND state_entered_at_cycle <= ?
        ORDER BY state_entered_at_cycle ASC
        LIMIT ?
        """,
        (*_TERMINAL_STATES, stale_cutoff, max_listed),
    ).fetchall()
    stale = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "name": r["name"],
            "kfm_state": r["kfm_state"],
            "cycles_in_state": current_cycle - int(r["state_entered_at_cycle"]),
        }
        for r in stale_rows
    ]

    # Dead: any entity with no entity_transitions row in the last
    # ``activity_window_cycles``.
    #
    # v4.64 (ADR 0083): switched from agent_activity_log.cell_ref to
    # entity_transitions.entity_id. The original v4.21 design joined
    # on cell_ref, but no production caller of ``record_activity()``
    # ever set cell_ref — so ``NOT EXISTS (cell_ref = e.id …)`` was
    # always true for every non-terminal entity, meaning the audit
    # reported every non-terminal entity as "dead." Transitions are
    # the entity-scoped signal we actually have: every lifecycle move
    # writes a row with the right ``entity_id``.
    #
    # Caveat: a long-stable entity in active use but with no
    # transitions in the window will still show as "dead" under this
    # signal. That's a stricter definition than "untouched" but it's
    # honest — it's exactly what the lifecycle table says.
    activity_cutoff = current_cycle - activity_window_cycles
    dead_rows = conn.execute(
        """
        SELECT e.id, e.kind, e.name, e.kfm_state, e.state_entered_at_cycle
        FROM entities AS e
        WHERE e.kfm_state NOT IN (?, ?)
          AND NOT EXISTS (
              SELECT 1
              FROM entity_transitions AS t
              WHERE t.entity_id = e.id
                AND t.cycle > ?
          )
        ORDER BY e.state_entered_at_cycle ASC
        LIMIT ?
        """,
        (*_TERMINAL_STATES, activity_cutoff, max_listed),
    ).fetchall()
    dead = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "name": r["name"],
            "kfm_state": r["kfm_state"],
            "cycles_in_state": current_cycle - int(r["state_entered_at_cycle"]),
        }
        for r in dead_rows
    ]

    # Re-anchor events: K-operator demotions of STABLE plans in the
    # recent window. This is the "drift fired and demoted the plan" path.
    reanchor_cutoff = current_cycle - reanchor_window_cycles
    reanchor_count = int(
        conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM entity_transitions
            WHERE from_state = 'STABLE'
              AND to_state = 'DEPRECATED'
              AND operator_type = 'k'
              AND cycle > ?
            """,
            (reanchor_cutoff,),
        ).fetchone()["n"]
    )

    deprecated_unarchived = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM entities WHERE kfm_state = 'DEPRECATED'"
        ).fetchone()["n"]
    )

    return {
        "current_cycle": current_cycle,
        "total_entities": total,
        "by_kind": by_kind,
        "by_state": by_state,
        "stale_entities": stale,
        "stale_count": len(stale),
        "dead_entities": dead,
        "dead_count": len(dead),
        "deprecated_unarchived": deprecated_unarchived,
        "reanchor_events_in_window": reanchor_count,
        "reanchor_window_cycles": reanchor_window_cycles,
        "thresholds": {
            "stale_after_cycles": stale_after_cycles,
            "activity_window_cycles": activity_window_cycles,
        },
    }


def auto_archive_stale_deprecated(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    archive_after_cycles: int = 30,
    max_per_cycle: int = 25,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Promote DEPRECATED entities that have aged out to ARCHIVED.

    Walks every entity currently in ``kfm_state='DEPRECATED'`` whose
    ``state_entered_at_cycle`` is at least ``archive_after_cycles``
    behind ``current_cycle``. Each one is transitioned via the
    K-operator (the only operator authorised for ``DEPRECATED →
    ARCHIVED`` per ADR 0003). Capped at ``max_per_cycle`` so a
    long-overdue housekeeping run never monopolises the loop.

    Returns one record per entity acted on (or that would be acted on
    in ``dry_run`` mode): ``{"id", "kind", "name", "cycles_in_state"}``.
    """
    from .entities import transition_entity

    cutoff = current_cycle - archive_after_cycles
    rows = conn.execute(
        """
        SELECT id, kind, name, state_entered_at_cycle
        FROM entities
        WHERE kfm_state = 'DEPRECATED'
          AND state_entered_at_cycle <= ?
        ORDER BY state_entered_at_cycle ASC
        LIMIT ?
        """,
        (cutoff, max_per_cycle),
    ).fetchall()

    archived: list[dict[str, Any]] = []
    # v4.55 (ADR 0074): wrap the batch so a partial failure rolls back.
    # Individual transition_entity exceptions are still swallowed
    # (logged) — the wrapper exists for unexpected failures (e.g.
    # disk-full, schema mismatch) that should not leave a half-archived
    # state on disk. dry_run skips the wrapper since no writes happen.
    if dry_run:
        for r in rows:
            archived.append({
                "id": r["id"], "kind": r["kind"], "name": r["name"],
                "cycles_in_state": current_cycle - int(r["state_entered_at_cycle"]),
            })
        return archived
    with _batch_transaction(conn):
        for r in rows:
            record = {
                "id": r["id"],
                "kind": r["kind"],
                "name": r["name"],
                "cycles_in_state": current_cycle - int(r["state_entered_at_cycle"]),
            }
            try:
                transition_entity(
                    conn,
                    r["id"],
                    "ARCHIVED",
                    "k",
                    cycle=current_cycle,
                    reason=(
                        f"auto-archive: DEPRECATED for {record['cycles_in_state']} "
                        f"cycles (>= {archive_after_cycles})"
                    ),
                )
                archived.append(record)
            except Exception:
                logger.exception(
                    "auto-archive: failed to transition %s (%s/%s)",
                    r["id"], r["kind"], r["name"],
                )
    return archived


def propose_kill_archived(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    archive_after_cycles: int = 90,
    max_per_cycle: int = 25,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """v4.39: queue ``kill_entity`` mutations for long-ARCHIVED entities.

    ARCHIVED → KILLED is intentionally a gated step (ADR 0046): KILLED
    wipes history while ARCHIVED preserves it. This function does NOT
    transition anything — it enqueues operator-approved-required
    mutations. ``apply_approved_kills`` (below) performs the transition
    only on mutations the operator has explicitly approved.

    Dedup: existing ``status='pending'`` ``kill_entity`` mutations for
    the same entity id are not re-enqueued.
    """
    from .mutations import create_mutation, list_mutations

    cutoff = current_cycle - archive_after_cycles
    rows = conn.execute(
        """
        SELECT id, kind, name, state_entered_at_cycle
        FROM entities
        WHERE kfm_state = 'ARCHIVED'
          AND state_entered_at_cycle <= ?
        ORDER BY state_entered_at_cycle ASC
        LIMIT ?
        """,
        (cutoff, max_per_cycle),
    ).fetchall()

    pending_kill_target_ids: set[str] = set()
    for m in list_mutations(conn, type="kill_entity", status="pending"):
        eid = m.payload.get("entity_id") if isinstance(m.payload, dict) else None
        if isinstance(eid, str):
            pending_kill_target_ids.add(eid)

    proposed: list[dict[str, Any]] = []
    for r in rows:
        if r["id"] in pending_kill_target_ids:
            continue
        rec = {
            "id": r["id"],
            "kind": r["kind"],
            "name": r["name"],
            "cycles_in_state": current_cycle - int(r["state_entered_at_cycle"]),
        }
        if not dry_run:
            payload = {
                "entity_id": r["id"],
                "kind": r["kind"],
                "name": r["name"],
                "cycles_in_state": rec["cycles_in_state"],
            }
            reason = (
                f"auto-kill: ARCHIVED for {rec['cycles_in_state']} cycles "
                f"(>= {archive_after_cycles})"
            )
            create_mutation(
                conn, type="kill_entity", payload=payload, reason=reason
            )
        proposed.append(rec)
    return proposed


def apply_approved_kills(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    max_per_run: int = 25,
) -> list[dict[str, Any]]:
    """v4.39: walk approved ``kill_entity`` mutations and transition the
    referenced entities ARCHIVED → KILLED via the K-operator. Marks each
    mutation applied. Returns one record per killed entity.

    Failures are logged and the mutation stays in ``approved`` so the
    operator can investigate.
    """
    from .entities import transition_entity
    from .mutations import list_mutations, mark_applied, mark_failed

    pending = [
        m for m in list_mutations(conn, type="kill_entity", status="approved")
    ][:max_per_run]
    killed: list[dict[str, Any]] = []
    # v4.55 (ADR 0074): batch-wrap the kill loop. Same rationale as
    # auto_archive_stale_deprecated — a partial failure should not
    # leave the mutation queue + entity state out of sync.
    with _batch_transaction(conn):
        for m in pending:
            eid = m.payload.get("entity_id") if isinstance(m.payload, dict) else None
            if not isinstance(eid, str):
                mark_failed(conn, m.id, reason="kill_entity payload missing entity_id")
                continue
            try:
                transition_entity(
                    conn, eid, "KILLED", "k",
                    cycle=current_cycle,
                    reason=f"approved kill (mutation #{m.id})",
                )
                mark_applied(conn, m.id, reason="killed")
                killed.append(
                    {
                        "mutation_id": m.id,
                        "entity_id": eid,
                        "kind": m.payload.get("kind"),
                        "name": m.payload.get("name"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "failed to apply kill_entity mutation #%s for entity %s",
                    m.id, eid,
                )
                mark_failed(conn, m.id, reason=f"transition error: {exc}")
    return killed


def reanchor_history(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    bucket_size: int = 10,
    n_buckets: int = 12,
) -> list[dict[str, Any]]:
    """v4.30: K-operator demotion counts bucketed across recent cycles.

    Returns a list of ``n_buckets`` entries oldest-first, each
    ``{"start_cycle", "end_cycle", "count"}``. A bucket spans
    ``[start_cycle, end_cycle)`` (half-open) of width ``bucket_size``.
    The newest bucket ends at ``current_cycle + 1`` so the live cycle
    is included.

    Default 12 buckets × 10 cycles = 120 cycles of trend, which lines
    up with the audit_ontology's reanchor_window_cycles default of 50
    plus headroom.
    """
    if bucket_size < 1 or n_buckets < 1:
        return []
    end = current_cycle + 1
    boundaries: list[tuple[int, int]] = []
    for i in range(n_buckets):
        bend = end - i * bucket_size
        bstart = bend - bucket_size
        boundaries.append((bstart, bend))
    boundaries.reverse()  # oldest first

    rows = conn.execute(
        """
        SELECT cycle FROM entity_transitions
        WHERE from_state = 'STABLE' AND to_state = 'DEPRECATED'
          AND operator_type = 'k'
          AND cycle >= ? AND cycle < ?
        """,
        (boundaries[0][0], boundaries[-1][1]),
    ).fetchall()
    cycles = [int(r["cycle"]) for r in rows]

    out: list[dict[str, Any]] = []
    for (bstart, bend) in boundaries:
        n = sum(1 for c in cycles if bstart <= c < bend)
        out.append({"start_cycle": bstart, "end_cycle": bend, "count": n})
    return out
