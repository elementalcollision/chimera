"""v4.69 (ADR 0088 §P1) — engine_runs telemetry.

Unified source of truth for Discovery / Curiosity / Reflection
engine activity. Pre-v4.69 the three engines left signal across
``api_calls``, ``ladder_outcomes`` (with ``task_type`` set), and
``mind/CHRONICLE.md``, plus an out-of-band
``state/engines/last_runs.json``. None of those agreed; the
post-mortem in ``mind/postmortems/engine-telemetry-2026-05-20.md``
named that the canonical wrong.

This module is the canonical right: one row per engine firing,
with status, cost, and effect counters.

Lifecycle:

  * ``start_engine_run(conn, engine, cycle)`` — opens a row in
    status "running"; returns the row id.
  * ``finish_engine_run(conn, run_id, *, status, ...)`` — updates
    the row in place with cost, effect counts, and final status.

The two-call shape mirrors how the engines actually execute (open
on entry, close on exit even when the engine raises).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineRunRecord:
    id: int
    engine: str
    cycle: int
    started_at: str
    finished_at: str | None
    status: str
    skip_reason: str | None
    api_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    chronicle_added: int
    mutations_proposed: int
    summary: str | None


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def start_engine_run(
    conn: sqlite3.Connection,
    *,
    engine: str,
    cycle: int,
) -> int:
    """Open a running engine row. Returns the row id.

    Status begins as ``"running"`` so a crash or interrupt leaves a
    visible orphan row instead of nothing — the operator can spot
    a long-running ``running`` status as a stuck engine.
    """
    cursor = conn.execute(
        "INSERT INTO engine_runs (engine, cycle, started_at, status) "
        "VALUES (?, ?, ?, ?)",
        (engine, cycle, _utc_now_iso(), "running"),
    )
    conn.commit()
    return cursor.lastrowid


def finish_engine_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    skip_reason: str | None = None,
    api_calls: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float | None = None,
    chronicle_added: int = 0,
    mutations_proposed: int = 0,
    summary: str | None = None,
) -> None:
    """Close an engine row with final status + effect counters.

    Idempotent — repeated calls overwrite, which is what we want if
    an engine wrapper catches an exception after partial state.
    """
    if status not in ("success", "skipped", "failed", "running"):
        # Defensive: don't reject so a future engine variant can add
        # a status; just record it as given.
        pass
    summary_truncated = (summary or "")[:200] if summary else None
    conn.execute(
        "UPDATE engine_runs SET "
        "  finished_at = ?, status = ?, skip_reason = ?, "
        "  api_calls = ?, tokens_in = ?, tokens_out = ?, cost_usd = ?, "
        "  chronicle_added = ?, mutations_proposed = ?, summary = ? "
        "WHERE id = ?",
        (
            _utc_now_iso(), status, skip_reason,
            int(api_calls), int(tokens_in), int(tokens_out), cost_usd,
            int(chronicle_added), int(mutations_proposed), summary_truncated,
            run_id,
        ),
    )
    conn.commit()


def list_engine_runs(
    conn: sqlite3.Connection,
    *,
    engine: str | None = None,
    limit: int = 50,
) -> list[EngineRunRecord]:
    """Most-recent runs first."""
    if engine is not None:
        rows = conn.execute(
            "SELECT * FROM engine_runs WHERE engine = ? "
            "ORDER BY id DESC LIMIT ?",
            (engine, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM engine_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        EngineRunRecord(
            id=r["id"], engine=r["engine"], cycle=r["cycle"],
            started_at=r["started_at"], finished_at=r["finished_at"],
            status=r["status"], skip_reason=r["skip_reason"],
            api_calls=r["api_calls"], tokens_in=r["tokens_in"],
            tokens_out=r["tokens_out"], cost_usd=r["cost_usd"],
            chronicle_added=r["chronicle_added"],
            mutations_proposed=r["mutations_proposed"],
            summary=r["summary"],
        )
        for r in rows
    ]


def engine_runs_summary(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Aggregate: ``{engine_name: {status: count, ...}, ...}``.

    Used by the doctor / dashboard for an at-a-glance health check.
    """
    rows = conn.execute(
        "SELECT engine, status, COUNT(*) AS n FROM engine_runs "
        "GROUP BY engine, status"
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["engine"], {})[r["status"]] = int(r["n"])
    return out


__all__ = [
    "EngineRunRecord",
    "engine_runs_summary",
    "finish_engine_run",
    "list_engine_runs",
    "start_engine_run",
]
