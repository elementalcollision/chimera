"""Tests for the LadybugDB graph store (ADR 0015)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    GRAPH_SCHEMA_VERSION,
    GraphStore,
    create_entity,
    open_and_init,
    transition_entity,
)


@pytest.fixture
def graph(tmp_path: Path) -> GraphStore:
    return GraphStore(tmp_path / "chimera.graph")


@pytest.fixture
def sqlite_conn(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_schema_version_is_one():
    assert GRAPH_SCHEMA_VERSION == 1


def test_init_schema_idempotent(graph: GraphStore):
    graph.init_schema()
    graph.init_schema()  # second call must not raise
    result = graph.query("MATCH (n:Entity) RETURN count(n)")
    assert result.rows[0][0] == 0


def test_rebuild_projects_entities_and_transitions(graph: GraphStore, sqlite_conn):
    e1 = create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    e2 = create_entity(sqlite_conn, kind="tool", name="shell", cycle=0)
    transition_entity(
        sqlite_conn,
        entity_id=e1.id,
        to_state="EXPERIMENTAL",
        operator_type="f",
        reason="seed",
        cycle=1,
    )

    counts = graph.rebuild_from_sqlite(sqlite_conn)
    assert counts["Entity"] == 2
    assert counts["TRANSITIONED_TO"] == 1

    rows = graph.query("MATCH (e:Entity) RETURN e.name ORDER BY e.name").rows
    assert [r[0] for r in rows] == ["alpha", "shell"]

    edges = graph.query(
        "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) "
        "RETURN t.from_state, t.to_state, t.operator_type"
    ).rows
    assert edges == [["NEW", "EXPERIMENTAL", "f"]]


def test_rebuild_is_idempotent(graph: GraphStore, sqlite_conn):
    create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    graph.rebuild_from_sqlite(sqlite_conn)
    counts = graph.rebuild_from_sqlite(sqlite_conn)
    assert counts["Entity"] == 1
    rows = graph.query("MATCH (e:Entity) RETURN count(e)").rows
    assert rows[0][0] == 1


def test_query_returns_columns_and_rows(graph: GraphStore, sqlite_conn):
    create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    graph.rebuild_from_sqlite(sqlite_conn)
    result = graph.query("MATCH (e:Entity) RETURN e.kind, e.name")
    assert result.columns == ["e.kind", "e.name"]
    assert result.rows == [["plan", "alpha"]]
