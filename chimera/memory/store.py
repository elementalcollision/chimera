"""SQLite-backed memory store.

Per ADR 0002 + ADR 0003 amendment:

  - ``entities`` + ``entity_transitions`` — KFM ontology state and audit
  - ``agent_activity_log`` — proof-of-work heartbeat (cycle/cell PK)
  - ``api_calls`` + ``ladder_outcomes`` — populated by Phase 2.4

Connections use WAL mode and ``foreign_keys=ON``.

Migrations: a hand-rolled :func:`init_schema` for MVP. Alembic is a dev
dep (per pyproject) and will own evolution once schema changes start.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


# Stamped on the SQLite ``user_version`` PRAGMA. Bump only when the
# on-disk shape of an existing table changes incompatibly (added
# tables / added nullable columns are NOT bumps). Per ADR 0025, this
# is the durable contract for v4.
SQLITE_SCHEMA_VERSION = 4


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    id                    TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL,
    name                  TEXT NOT NULL,
    kfm_state             TEXT NOT NULL,
    state_entered_at_cycle INTEGER NOT NULL,
    details               TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS entity_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id       TEXT NOT NULL REFERENCES entities(id),
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    operator_type   TEXT NOT NULL,
    reason          TEXT,
    cycle           INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transitions_entity ON entity_transitions(entity_id, cycle);

CREATE TABLE IF NOT EXISTS agent_activity_log (
    cycle           INTEGER NOT NULL,
    cell_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    activity_type   TEXT NOT NULL,
    layer           TEXT,
    cell_ref        TEXT,
    details         TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (cycle, cell_id)
);
CREATE INDEX IF NOT EXISTS idx_activity_agent_cycle ON agent_activity_log(agent_id, cycle);

-- ADR 0003 amendment: api_calls + ladder_outcomes (populated by Phase 3+).
CREATE TABLE IF NOT EXISTS api_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle            INTEGER NOT NULL,
    provider         TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    cost_usd         REAL,
    latency_ms       INTEGER,
    finish_reason    TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    -- v4.33: how many tool_use blocks the model emitted in this response.
    -- 0 = pure text reply, 1 = single tool call, 2+ = parallel batch.
    tool_uses_count  INTEGER,
    -- v4.50: wall-clock between the prior round's last tool completion
    -- and the moment this provider call was dispatched. NULL on the
    -- first round of a task (no prior round to measure from). Helps
    -- diagnose where ACT actually spends its wall-clock.
    round_boundary_latency_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_calls_cycle ON api_calls(cycle);

CREATE TABLE IF NOT EXISTS ladder_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle           INTEGER NOT NULL,
    tier            TEXT NOT NULL,
    rung_model_id   TEXT NOT NULL,
    outcome         TEXT NOT NULL,  -- success | transient_fail | retry_exhausted | non_retriable
    task_type       TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ladder_outcomes_tier ON ladder_outcomes(tier);

-- v1.2: mutation queue for "Chimera proposes, operator disposes".
CREATE TABLE IF NOT EXISTS mutations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    type             TEXT NOT NULL,   -- skill_proposal | config_change | ...
    payload          TEXT NOT NULL,   -- JSON
    status           TEXT NOT NULL,   -- pending | approved | rejected | applied | expired | failed
    reason           TEXT,
    created_at       TEXT NOT NULL,
    approved_at      TEXT,
    applied_at       TEXT,
    -- v4.19: how many times a duplicate proposal hit this same signature
    -- (incremented in-place by adaptation._already_proposed instead of
    -- enqueueing a new row).
    recurrence_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mutations_status ON mutations(status);
CREATE INDEX IF NOT EXISTS idx_mutations_type ON mutations(type);

-- v4.46: task-escalation memory. Each row records a NON-COMPLETED ACT exit
-- so the next attempt at a similar task can start at a higher tier instead
-- of repeating the same failure.
CREATE TABLE IF NOT EXISTS task_escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signature       TEXT NOT NULL,       -- sorted-token frozenset of task_text
    task_text       TEXT NOT NULL,
    tier            TEXT NOT NULL,       -- tier used on the failed attempt
    finish_reason   TEXT NOT NULL,       -- max_rounds | provider_error | artifact_missing | degenerate_loop_abort
    rounds_used     INTEGER NOT NULL,
    cycle           INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_escalations_signature ON task_escalations(signature);
"""


def default_db_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / "chimera.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open (or create) the Chimera DB. WAL mode, foreign keys on."""
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # autocommit; we use explicit transactions
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema bootstrap. Safe to call on every startup."""
    conn.executescript(SCHEMA_SQL)
    # v4.19: idempotent additive migration for the recurrence_count column
    # on pre-existing DBs created before the column was in SCHEMA_SQL.
    try:
        conn.execute(
            "ALTER TABLE mutations ADD COLUMN recurrence_count "
            "INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        # column already exists — fine.
        pass
    # v4.33: idempotent additive migration for tool_uses_count on api_calls.
    try:
        conn.execute("ALTER TABLE api_calls ADD COLUMN tool_uses_count INTEGER")
    except sqlite3.OperationalError:
        pass
    # v4.50: round_boundary_latency_ms additive migration.
    try:
        conn.execute(
            "ALTER TABLE api_calls ADD COLUMN round_boundary_latency_ms INTEGER"
        )
    except sqlite3.OperationalError:
        pass
    conn.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION}")


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the on-disk schema version. 0 means uninitialised."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def open_and_init(path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(path)
    init_schema(conn)
    return conn
