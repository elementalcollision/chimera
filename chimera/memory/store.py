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
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle           INTEGER NOT NULL,
    provider        TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    latency_ms      INTEGER,
    finish_reason   TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL
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


def open_and_init(path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(path)
    init_schema(conn)
    return conn
