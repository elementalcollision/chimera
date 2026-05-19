"""KFM entity persistence — CRUD over SQLite.

Per ADR 0002: ontology state is relational. Transitions are validated by
the pure :mod:`chimera.core.kfm` checker, then committed atomically with
the transition row. The HTTP-router separation in village's clerk is
collapsed here into a single function that does both — Chimera is a
single-orchestrator service (per ADR 0001).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.kfm import OperatorType  # noqa: F401 — annotation-only


class EntityError(Exception):
    """Base error for entity ops."""


class EntityNotFound(EntityError):
    pass


class EntityAlreadyExists(EntityError):
    pass


class IllegalTransition(EntityError):
    pass


@dataclass(frozen=True)
class EntityRecord:
    id: str
    kind: str
    name: str
    kfm_state: str
    state_entered_at_cycle: int
    details: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class TransitionRecord:
    id: int
    entity_id: str
    from_state: str
    to_state: str
    operator_type: str
    reason: str | None
    cycle: int
    created_at: str


# ── helpers ─────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _row_to_entity(row: sqlite3.Row) -> EntityRecord:
    return EntityRecord(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        kfm_state=row["kfm_state"],
        state_entered_at_cycle=row["state_entered_at_cycle"],
        details=json.loads(row["details"]) if row["details"] else {},
        created_at=row["created_at"],
    )


def _row_to_transition(row: sqlite3.Row) -> TransitionRecord:
    return TransitionRecord(
        id=row["id"],
        entity_id=row["entity_id"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        operator_type=row["operator_type"],
        reason=row["reason"],
        cycle=row["cycle"],
        created_at=row["created_at"],
    )


# ── CRUD ────────────────────────────────────────────────────


def create_entity(
    conn: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    cycle: int,
    initial_state: str = "NEW",
    details: dict[str, Any] | None = None,
) -> EntityRecord:
    """Insert a new entity. Raises if (kind, name) already exists."""
    from ..core.kfm import KFM_STATES
    if initial_state not in KFM_STATES:
        raise ValueError(f"unknown initial_state: {initial_state!r}")
    entity_id = str(uuid.uuid4())  # TODO: UUIDv7 when stdlib supports it
    created = _utc_now_iso()
    try:
        conn.execute(
            "INSERT INTO entities (id, kind, name, kfm_state, state_entered_at_cycle, "
            "details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entity_id,
                kind,
                name,
                initial_state,
                cycle,
                json.dumps(details) if details else None,
                created,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise EntityAlreadyExists(f"{kind}/{name} already exists") from exc
    return EntityRecord(
        id=entity_id,
        kind=kind,
        name=name,
        kfm_state=initial_state,
        state_entered_at_cycle=cycle,
        details=details or {},
        created_at=created,
    )


def get_entity(conn: sqlite3.Connection, entity_id: str) -> EntityRecord | None:
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return _row_to_entity(row) if row else None


def get_entity_by_name(
    conn: sqlite3.Connection, *, kind: str, name: str
) -> EntityRecord | None:
    row = conn.execute(
        "SELECT * FROM entities WHERE kind = ? AND name = ?", (kind, name)
    ).fetchone()
    return _row_to_entity(row) if row else None


def list_entities(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    kfm_state: str | None = None,
) -> list[EntityRecord]:
    sql = "SELECT * FROM entities"
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if kfm_state is not None:
        clauses.append("kfm_state = ?")
        params.append(kfm_state)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_entity(r) for r in rows]


def transition_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    to_state: str,
    operator_type: OperatorType,
    *,
    cycle: int,
    reason: str | None = None,
) -> TransitionRecord:
    """Validate via :func:`check_transition`, then atomically commit
    the new state + a transition audit row.

    Raises :class:`IllegalTransition` if the move is not allowed.
    """
    from ..core.kfm import check_transition

    entity = get_entity(conn, entity_id)
    if entity is None:
        raise EntityNotFound(entity_id)

    result = check_transition(entity.kfm_state, to_state, operator_type)
    if not result.allowed:
        raise IllegalTransition(
            f"{entity.kfm_state} → {to_state} by {operator_type!r}: {result.reason}"
        )

    created = _utc_now_iso()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE entities SET kfm_state = ?, state_entered_at_cycle = ? WHERE id = ?",
            (to_state, cycle, entity_id),
        )
        cursor = conn.execute(
            "INSERT INTO entity_transitions "
            "(entity_id, from_state, to_state, operator_type, reason, cycle, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entity_id,
                entity.kfm_state,
                to_state,
                operator_type,
                reason,
                cycle,
                created,
            ),
        )
        transition_id = cursor.lastrowid
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return TransitionRecord(
        id=transition_id,
        entity_id=entity_id,
        from_state=entity.kfm_state,
        to_state=to_state,
        operator_type=operator_type,
        reason=reason,
        cycle=cycle,
        created_at=created,
    )


def list_transitions(
    conn: sqlite3.Connection, entity_id: str
) -> list[TransitionRecord]:
    rows = conn.execute(
        "SELECT * FROM entity_transitions WHERE entity_id = ? ORDER BY cycle, id",
        (entity_id,),
    ).fetchall()
    return [_row_to_transition(r) for r in rows]


def record_activity(
    conn: sqlite3.Connection,
    *,
    cycle: int,
    cell_id: str,
    agent_id: str,
    activity_type: str,
    layer: str | None = None,
    cell_ref: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Idempotent activity log insert per (cycle, cell_id).

    Returns True if the row was inserted, False if a row already existed
    for that PK (the collision pattern from village's miner).
    """
    try:
        conn.execute(
            "INSERT INTO agent_activity_log "
            "(cycle, cell_id, agent_id, activity_type, layer, cell_ref, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cycle,
                cell_id,
                agent_id,
                activity_type,
                layer,
                cell_ref,
                json.dumps(details) if details else None,
                _utc_now_iso(),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def record_api_call(
    conn: sqlite3.Connection,
    *,
    cycle: int,
    provider: str,
    model_id: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    finish_reason: str | None = None,
    error: str | None = None,
) -> int:
    """Insert an api_calls row. Returns the row id."""
    cursor = conn.execute(
        "INSERT INTO api_calls (cycle, provider, model_id, input_tokens, "
        "output_tokens, cost_usd, latency_ms, finish_reason, error, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cycle,
            provider,
            model_id,
            input_tokens,
            output_tokens,
            cost_usd,
            latency_ms,
            finish_reason,
            error,
            _utc_now_iso(),
        ),
    )
    return cursor.lastrowid


def record_ladder_outcome(
    conn: sqlite3.Connection,
    *,
    cycle: int,
    tier: str,
    rung_model_id: str,
    outcome: str,  # success | transient_fail | retry_exhausted | non_retriable
    task_type: str | None = None,
) -> int:
    if outcome not in {"success", "transient_fail", "retry_exhausted", "non_retriable"}:
        raise ValueError(f"unknown outcome: {outcome!r}")
    cursor = conn.execute(
        "INSERT INTO ladder_outcomes (cycle, tier, rung_model_id, outcome, task_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cycle, tier, rung_model_id, outcome, task_type, _utc_now_iso()),
    )
    return cursor.lastrowid


def ensure_current_plan(
    conn: sqlite3.Connection,
    cycle: int,
    *,
    name: str = "current",
) -> EntityRecord:
    """Idempotent: fetch the current plan entity, or bootstrap it in STABLE.

    Bootstrap is the privileged escape hatch from the KFM thesis — the first
    plan of a session is created directly in STABLE. Subsequent re-anchors
    after a K demotion go through the normal NEW → EXPERIMENTAL → CANDIDATE
    → STABLE walk.
    """
    existing = get_entity_by_name(conn, kind="plan", name=name)
    if existing is not None:
        return existing
    return create_entity(
        conn,
        kind="plan",
        name=name,
        cycle=cycle,
        initial_state="STABLE",
        details={"bootstrapped": True},
    )


def activity_window(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    current_cycle: int,
    last_n_cycles: int = 3,
) -> dict[str, Any]:
    """M-Operator probe: summary of an agent's recent activity.

    Mirrors the shape returned by village's
    ``GET /agents/{id}/activity?current_cycle=...&last_n_cycles=...``.
    """
    cutoff = max(0, current_cycle - last_n_cycles + 1)
    rows = conn.execute(
        "SELECT cycle, layer FROM agent_activity_log "
        "WHERE agent_id = ? AND cycle >= ? AND cycle <= ?",
        (agent_id, cutoff, current_cycle),
    ).fetchall()
    active_cycles = {r["cycle"] for r in rows}
    layer_counts: dict[str, int] = {}
    for r in rows:
        layer = r["layer"] or "unspecified"
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    return {
        "agent_id": agent_id,
        "current_cycle": current_cycle,
        "last_n_cycles": last_n_cycles,
        "activity_count": len(rows),
        "active_cycles_in_window": len(active_cycles),
        "layer_counts": layer_counts,
    }
