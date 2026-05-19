"""SQLite schema version + table-shape migration tests (ADR 0025, v4.0)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from chimera.memory import (
    GRAPH_SCHEMA_VERSION,
    GraphStore,
    SQLITE_SCHEMA_VERSION,
    open_and_init,
    schema_version,
)


_EXPECTED_TABLES = {
    "entities",
    "entity_transitions",
    "agent_activity_log",
    "api_calls",
    "ladder_outcomes",
    "mutations",
}


@pytest.fixture
def db(tmp_path: Path):
    conn = open_and_init(tmp_path / "chimera.db")
    yield conn
    conn.close()


def test_schema_version_stamped_on_fresh_db(db):
    assert schema_version(db) == SQLITE_SCHEMA_VERSION
    assert SQLITE_SCHEMA_VERSION == 4


def test_schema_version_is_idempotent(db, tmp_path: Path):
    # Re-init the same path; version should not jump.
    conn2 = open_and_init(tmp_path / "chimera.db")
    try:
        assert schema_version(conn2) == SQLITE_SCHEMA_VERSION
    finally:
        conn2.close()


def test_all_expected_tables_present(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {r["name"] for r in rows}
    missing = _EXPECTED_TABLES - present
    assert not missing, f"missing tables: {missing}"


def test_legacy_v0_db_upgrades_on_open(tmp_path: Path):
    """A pre-versioning DB (user_version=0) gets the v4 stamp + tables."""
    raw = tmp_path / "legacy.db"
    legacy = sqlite3.connect(raw)
    # Simulate an old install with only the entities table.
    legacy.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, kind TEXT, name TEXT, "
        "kfm_state TEXT, state_entered_at_cycle INTEGER, created_at TEXT)"
    )
    legacy.close()

    conn = open_and_init(raw)
    try:
        assert schema_version(conn) == SQLITE_SCHEMA_VERSION
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        present = {r["name"] for r in rows}
        assert _EXPECTED_TABLES <= present
    finally:
        conn.close()


def test_graph_schema_version_is_stable():
    assert GRAPH_SCHEMA_VERSION == 1


def test_graph_store_init_is_idempotent(tmp_path: Path):
    g = GraphStore(tmp_path / "graph")
    g.init_schema()
    g.init_schema()  # second call must not raise
    result = g.query("MATCH (n:Entity) RETURN count(n)")
    assert result.rows[0][0] == 0
