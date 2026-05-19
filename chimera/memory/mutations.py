"""Mutation queue — "Chimera proposes, the operator disposes."

Per ADR 0003 §"Mutation queue: adopted with simplified policy" — at MVP
the operator is a human at the CLI. Each row is a proposal Chimera made
that the operator decides whether to apply.

Statuses:
  - ``pending``  — created, awaiting operator
  - ``approved`` — operator approved; mutation runner will apply
  - ``rejected`` — operator declined
  - ``applied``  — successfully applied (handler updated config / activated skill / ...)
  - ``expired``  — pending too long (sweep_stale)
  - ``failed``   — approved but application errored
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mutation:
    id: int
    type: str
    payload: dict[str, Any]
    status: str
    reason: str | None
    created_at: str
    approved_at: str | None
    applied_at: str | None


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _row_to_mutation(row: sqlite3.Row) -> Mutation:
    return Mutation(
        id=row["id"],
        type=row["type"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        status=row["status"],
        reason=row["reason"],
        created_at=row["created_at"],
        approved_at=row["approved_at"],
        applied_at=row["applied_at"],
    )


def create_mutation(
    conn: sqlite3.Connection,
    *,
    type: str,
    payload: dict[str, Any],
    reason: str | None = None,
) -> Mutation:
    cursor = conn.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES (?, ?, 'pending', ?, ?)",
        (type, json.dumps(payload, sort_keys=True), reason, _utc_now_iso()),
    )
    row = conn.execute(
        "SELECT * FROM mutations WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_mutation(row)


def get_mutation(conn: sqlite3.Connection, mid: int) -> Mutation | None:
    row = conn.execute("SELECT * FROM mutations WHERE id = ?", (mid,)).fetchone()
    return _row_to_mutation(row) if row else None


def list_mutations(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    type: str | None = None,
    limit: int = 100,
) -> list[Mutation]:
    sql = "SELECT * FROM mutations"
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if type is not None:
        clauses.append("type = ?")
        params.append(type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [_row_to_mutation(r) for r in conn.execute(sql, params).fetchall()]


def approve_mutation(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    """Operator approves a pending mutation. Idempotent for already-approved."""
    m = get_mutation(conn, mid)
    if m is None:
        raise ValueError(f"unknown mutation: {mid}")
    if m.status not in ("pending", "approved"):
        raise ValueError(f"mutation {mid} is {m.status!r}; cannot approve")
    conn.execute(
        "UPDATE mutations SET status = 'approved', approved_at = ?, reason = ? "
        "WHERE id = ?",
        (_utc_now_iso(), reason or m.reason, mid),
    )
    return get_mutation(conn, mid)


def reject_mutation(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    m = get_mutation(conn, mid)
    if m is None:
        raise ValueError(f"unknown mutation: {mid}")
    if m.status not in ("pending",):
        raise ValueError(f"mutation {mid} is {m.status!r}; cannot reject")
    conn.execute(
        "UPDATE mutations SET status = 'rejected', reason = ? WHERE id = ?",
        (reason or m.reason, mid),
    )
    return get_mutation(conn, mid)


def mark_applied(
    conn: sqlite3.Connection, mid: int, *, reason: str | None = None
) -> Mutation:
    conn.execute(
        "UPDATE mutations SET status = 'applied', applied_at = ?, reason = ? "
        "WHERE id = ?",
        (_utc_now_iso(), reason, mid),
    )
    return get_mutation(conn, mid)


def mark_failed(
    conn: sqlite3.Connection, mid: int, *, reason: str
) -> Mutation:
    conn.execute(
        "UPDATE mutations SET status = 'failed', reason = ? WHERE id = ?",
        (reason, mid),
    )
    return get_mutation(conn, mid)


def sweep_stale(
    conn: sqlite3.Connection, *, older_than_cycles: int, current_cycle: int
) -> int:
    """Expire pending mutations that have been around too long.

    Returns the count expired. Per Reggio HOUSEKEEPING phase semantics —
    "stale" is measured here in plain ISO timestamps for simplicity (one
    cycle ≈ 15min default; older_than_cycles*15min wall-clock).
    """
    cutoff_minutes = older_than_cycles * 15
    cutoff = (
        dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(minutes=cutoff_minutes)
    ).isoformat(timespec="seconds")
    cursor = conn.execute(
        "UPDATE mutations SET status = 'expired' "
        "WHERE status = 'pending' AND created_at < ?",
        (cutoff,),
    )
    return cursor.rowcount
