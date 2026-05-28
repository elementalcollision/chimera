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
    round_boundary_latency_ms  INTEGER,
    -- v4.60 (ADR 0079): signature of the INBOX task that triggered
    -- this call. Lets task_spend_usd() sum spend across cycles for
    -- the per-task budget cap. Same Jaccard-friendly token-bag
    -- format as task_escalations.signature.
    task_signature  TEXT,
    -- v4.69 (ADR 0088 §P4): who made this call. "act" for ActExecutor,
    -- "discovery"/"curiosity"/"reflection" for the engines, "splitter"
    -- for the v4.63 task-splitter helper, etc. Lets cost queries
    -- separate ACT spend from engine spend without guessing from
    -- model_id. NULL on pre-v4.69 rows.
    caller          TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_calls_cycle ON api_calls(cycle);
-- idx_api_calls_caller is created after the v4.69 ALTER below so
-- pre-v4.69 DBs don't trip on the missing column during executescript.

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

-- v4.69 (ADR 0088 §P1): unified engine telemetry.
--
-- Pre-v4.69 the three engines (Discovery / Curiosity / Reflection)
-- left three different signals — a row in api_calls, a row in
-- ladder_outcomes with task_type set, and a section in
-- mind/CHRONICLE.md — and an out-of-band ``state/engines/last_runs.json``
-- date file. None agreed. This table is the single source of truth:
-- one row per engine firing, with status, cost, and effect counters.
CREATE TABLE IF NOT EXISTS engine_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    engine              TEXT NOT NULL,        -- discovery|curiosity|reflection
    cycle               INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    -- success: engine fired AND wrote chronicle / proposed mutation
    -- skipped: engine declined to fire (gate, env, missing provider)
    -- failed: engine threw or the model errored
    status              TEXT NOT NULL,
    skip_reason         TEXT,
    api_calls           INTEGER NOT NULL DEFAULT 0,
    tokens_in           INTEGER NOT NULL DEFAULT 0,
    tokens_out          INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL,
    chronicle_added     INTEGER NOT NULL DEFAULT 0,    -- lines appended
    mutations_proposed  INTEGER NOT NULL DEFAULT 0,
    summary             TEXT                            -- 200-char excerpt
);
CREATE INDEX IF NOT EXISTS idx_engine_runs_engine ON engine_runs(engine);
CREATE INDEX IF NOT EXISTS idx_engine_runs_cycle ON engine_runs(cycle);

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
    finish_reason   TEXT NOT NULL,       -- max_rounds | provider_error | artifact_missing | degenerate_loop_abort | ping_pong_abort
    rounds_used     INTEGER NOT NULL,
    cycle           INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_escalations_signature ON task_escalations(signature);

-- v4.71 (ADR 0090, P3): persistent demote/promote state per proposer
-- (mutation.type). When the rolling acceptance rate drops below the
-- threshold the row is upserted with status='degraded'; operator runs
-- `chimera proposers promote <type>` to restore.
CREATE TABLE IF NOT EXISTS proposer_status (
    proposer        TEXT PRIMARY KEY,         -- mutation.type
    status          TEXT NOT NULL,            -- 'active' | 'degraded' | 'paused'
    reason          TEXT,
    last_rate       REAL,                     -- last computed acceptance rate
    last_decided    INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / "chimera.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open (or create) the Chimera DB. WAL mode, foreign keys on."""
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # ``check_same_thread=False`` is load-bearing for the v4.115
    # persistent-loop architecture (``chimera/_async_loop.py``):
    # ``ChimeraLoop.__init__`` opens this connection on the calling
    # thread (the main thread, when invoked from ``chimera run``)
    # but ``run_on_persistent_loop(loop.run_one_cycle())`` then
    # executes every query on the loop's daemon background thread.
    # Python's default ``check_same_thread=True`` makes that combo
    # raise ``sqlite3.ProgrammingError`` on the first cross-thread
    # ``conn.execute`` (see PR #104 v35-soak postmortem, 2026-05-28).
    # Concurrency safety relies on the persistent loop serializing
    # all coroutines onto a single thread — there is no second
    # concurrent writer to race against. The only main-thread touch
    # after init is ``Loop.close()``, which runs strictly after the
    # cycle future has resolved (``cli.py``'s ``finally``), so it
    # cannot race with the loop thread either.
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # autocommit; we use explicit transactions
        check_same_thread=False,
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
    # v4.60 (ADR 0079): task_signature additive migration for per-task budget.
    try:
        conn.execute("ALTER TABLE api_calls ADD COLUMN task_signature TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_calls_task_signature "
            "ON api_calls(task_signature)"
        )
    except sqlite3.OperationalError:
        pass
    # v4.61 (ADR 0080): wiki FTS5 search index. Idempotent; degrades to
    # no-op log warning if FTS5 isn't compiled into this SQLite build.
    try:
        from .wiki_search import ensure_wiki_index
        ensure_wiki_index(conn)
    except Exception:  # noqa: BLE001
        # Don't let a missing FTS5 module break the rest of init.
        pass
    # v4.69 (ADR 0088 §P4): caller column on api_calls.
    try:
        conn.execute("ALTER TABLE api_calls ADD COLUMN caller TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_calls_caller ON api_calls(caller)"
        )
    except sqlite3.OperationalError:
        pass
    # v4.69 (ADR 0088 §P1): engine_runs is in the CREATE block above and
    # the standard CREATE TABLE IF NOT EXISTS handles the migration —
    # no separate ALTER needed.
    conn.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION}")


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the on-disk schema version. 0 means uninitialised."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def open_and_init(path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(path)
    init_schema(conn)
    return conn
