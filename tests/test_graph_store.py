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


def test_filesystem_projection_skills_and_wiki(
    graph: GraphStore, sqlite_conn, tmp_path: Path
):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "__init__.py").write_text("")
    (skills / "skill_a.py").write_text(
        '"""a"""\n'
        'from chimera.tools.dynamic import skill_b\n'
        'TOOL = "shell"\n'
    )
    (skills / "skill_b.py").write_text('"""b"""\n')

    mind = tmp_path / "mind"
    mind.mkdir()
    (mind / "one.md").write_text("see [two](two.md) for details")
    (mind / "two.md").write_text("standalone")

    create_entity(sqlite_conn, kind="tool", name="shell", cycle=0)
    graph.init_schema()
    graph.clear_all()
    # Project entities manually so USES_TOOL has a target.
    graph._conn.execute(
        "CREATE (e:Entity {id: 't1', kind: 'tool', name: 'shell', "
        "kfm_state: 'STABLE', state_entered_at_cycle: 0, created_at: 'now'})"
    )
    counts = graph._project_skills_and_wiki(skills_dir=skills, mind_dir=mind)

    assert counts["Skill"] == 2
    assert counts["WikiDoc"] == 2
    assert counts["DEPENDS_ON"] == 1
    assert counts["REFERENCES"] == 1

    deps = graph.query(
        "MATCH (a:Skill)-[:DEPENDS_ON]->(b:Skill) RETURN a.name, b.name"
    ).rows
    assert deps == [["skill_a", "skill_b"]]

    uses = graph.query(
        "MATCH (s:Skill)-[:USES_TOOL]->(e:Entity) RETURN s.name, e.name"
    ).rows
    assert uses == [["skill_a", "shell"]]

    refs = graph.query(
        "MATCH (a:WikiDoc)-[:REFERENCES]->(b:WikiDoc) RETURN a.path, b.path"
    ).rows
    assert refs == [["one.md", "two.md"]]


def test_entity_history_query_returns_ordered_chain(graph: GraphStore, sqlite_conn):
    e = create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    transition_entity(
        sqlite_conn, entity_id=e.id, to_state="EXPERIMENTAL",
        operator_type="f", reason="r1", cycle=1,
    )
    transition_entity(
        sqlite_conn, entity_id=e.id, to_state="CANDIDATE",
        operator_type="m", reason="r2", cycle=2,
    )
    graph.rebuild_from_sqlite(sqlite_conn)
    hist = graph.query(
        "MATCH (e:Entity {id: $i})-[t:TRANSITIONED_TO]->(e) "
        "RETURN t.cycle, t.from_state, t.to_state ORDER BY t.cycle",
        params={"i": e.id},
    ).rows
    assert hist == [[1, "NEW", "EXPERIMENTAL"], [2, "EXPERIMENTAL", "CANDIDATE"]]
