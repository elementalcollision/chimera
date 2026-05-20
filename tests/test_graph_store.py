"""Tests for the LadybugDB graph store (ADR 0015)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    GRAPH_SCHEMA_VERSION,
    GraphStore,
    create_entity,
    create_mutation,
    mark_applied,
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


def test_mutation_edges_projected(graph: GraphStore, sqlite_conn):
    e = create_entity(sqlite_conn, kind="tool", name="my_tool", cycle=0)
    m_propose = create_mutation(
        sqlite_conn,
        type="tool_proposal",
        payload={"entity_name": "my_tool", "spec": "..."},
    )
    m_skill = create_mutation(
        sqlite_conn,
        type="skill_proposal",
        payload={"name": "do_thing", "description": "x", "brief": "y"},
    )
    mark_applied(sqlite_conn, m_skill.id, reason="ok")

    # Seed the dynamic-skill source so rebuild's projection creates the Skill node.
    from chimera.skills import dynamic_skills_dir
    skill_file = dynamic_skills_dir() / "do_thing.py"
    skill_file.write_text('"""seeded"""\n')
    try:
        counts = graph.rebuild_from_sqlite(sqlite_conn)
    finally:
        skill_file.unlink(missing_ok=True)
    assert counts["PROPOSED"] == 1
    assert counts["ACTIVATED"] == 1

    proposed = graph.query(
        "MATCH (m:Mutation)-[:PROPOSED]->(e:Entity) RETURN m.id, e.name"
    ).rows
    assert proposed == [[m_propose.id, "my_tool"]]


def test_trust_journal_round_trip(tmp_path: Path, monkeypatch):
    from chimera.a2a import latest_per_peer, list_decisions, record_decision

    monkeypatch.setenv("CHIMERA_PEER_TRUST_JOURNAL_DIR", str(tmp_path))
    record_decision("peerA", "ALLOW", reason="ok", drift_score=0.1)
    record_decision("peerA", "DEGRADE", reason="drifted", drift_score=0.6)
    record_decision("peerB", "REFUSE", reason="missing state")

    all_recs = list_decisions()
    assert len(all_recs) == 3

    latest = latest_per_peer()
    assert latest["peerA"].decision == "DEGRADE"
    assert latest["peerA"].drift_score == 0.6
    assert latest["peerB"].decision == "REFUSE"


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


# ── v4.31: incremental projection ───────────────────────────


def test_update_from_sqlite_appends_new_entities(graph: GraphStore, sqlite_conn):
    """First update populates the graph; second update appends only diffs."""
    create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    counts1 = graph.update_from_sqlite(sqlite_conn)
    assert counts1["Entity"] == 1

    # Re-run with no new rows → zero adds.
    counts2 = graph.update_from_sqlite(sqlite_conn)
    assert counts2["Entity"] == 0
    assert counts2["TRANSITIONED_TO"] == 0

    # Add a second entity → only that one is appended.
    create_entity(sqlite_conn, kind="skill", name="beta", cycle=1)
    counts3 = graph.update_from_sqlite(sqlite_conn)
    assert counts3["Entity"] == 1
    rows = graph.query("MATCH (e:Entity) RETURN e.name ORDER BY e.name").rows
    assert [r[0] for r in rows] == ["alpha", "beta"]


def test_update_from_sqlite_appends_new_transitions(graph: GraphStore, sqlite_conn):
    e = create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    transition_entity(
        sqlite_conn, entity_id=e.id, to_state="EXPERIMENTAL",
        operator_type="f", cycle=1,
    )
    graph.update_from_sqlite(sqlite_conn)

    transition_entity(
        sqlite_conn, entity_id=e.id, to_state="CANDIDATE",
        operator_type="m", cycle=2,
    )
    counts = graph.update_from_sqlite(sqlite_conn)
    assert counts["Entity"] == 0
    assert counts["TRANSITIONED_TO"] == 1

    rows = graph.query(
        "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) "
        "RETURN t.cycle ORDER BY t.cycle"
    ).rows
    assert [r[0] for r in rows] == [1, 2]


def test_update_from_sqlite_is_idempotent(graph: GraphStore, sqlite_conn):
    e = create_entity(sqlite_conn, kind="plan", name="alpha", cycle=0)
    transition_entity(
        sqlite_conn, entity_id=e.id, to_state="EXPERIMENTAL",
        operator_type="f", cycle=1,
    )
    graph.update_from_sqlite(sqlite_conn)
    graph.update_from_sqlite(sqlite_conn)
    graph.update_from_sqlite(sqlite_conn)
    n_ent = graph.query("MATCH (e:Entity) RETURN count(e)").rows[0][0]
    n_edge = graph.query(
        "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) RETURN count(t)"
    ).rows[0][0]
    assert n_ent == 1
    assert n_edge == 1


# ── v4.35: incremental for mutating rows ─────────────────────


def test_update_picks_up_mutation_status_flip(graph: GraphStore, sqlite_conn):
    """Mutation row's status: pending → applied should be visible after
    update_from_sqlite even though Entity append-only logic wouldn't
    catch it."""
    m = create_mutation(
        sqlite_conn, type="skill_proposal", payload={"name": "x"}
    )
    graph.update_from_sqlite(sqlite_conn)
    status_before = graph.query(
        "MATCH (m:Mutation {id: $i}) RETURN m.status",
        params={"i": int(m.id)},
    ).rows[0][0]
    assert status_before == "pending"

    mark_applied(sqlite_conn, m.id, reason="ok")
    graph.update_from_sqlite(sqlite_conn)

    status_after = graph.query(
        "MATCH (m:Mutation {id: $i}) RETURN m.status",
        params={"i": int(m.id)},
    ).rows[0][0]
    assert status_after == "applied"

    # And no duplicate mutation row was created.
    n_mut = graph.query("MATCH (m:Mutation) RETURN count(m)").rows[0][0]
    assert n_mut == 1


def test_update_skills_wiki_mtime_gate_is_noop_when_unchanged(
    graph: GraphStore, sqlite_conn, tmp_path,
):
    """v4.38: second update with no filesystem change → no Skill/WikiDoc
    counts in the result."""
    counts1 = graph.update_from_sqlite(sqlite_conn)
    # First run projects whatever the local filesystem has.
    counts2 = graph.update_from_sqlite(sqlite_conn)
    # Mtime gate: skills/wiki keys should be ABSENT in counts2 (no work
    # done) if the fingerprint matches.
    assert "Skill" not in counts2 or counts2.get("Skill", 0) == counts1.get("Skill", 0)
    assert "WikiDoc" not in counts2
    # Sanity: a fingerprint file was written.
    fp = graph.path.with_suffix(graph.path.suffix + ".fingerprint")
    assert fp.exists()
    digest_first = fp.read_text(encoding="utf-8").strip()
    assert len(digest_first) == 40  # sha1 hex


def test_update_with_mutations_disabled_skips_replace(graph: GraphStore, sqlite_conn):
    m = create_mutation(
        sqlite_conn, type="skill_proposal", payload={"name": "x"}
    )
    graph.update_from_sqlite(sqlite_conn)
    mark_applied(sqlite_conn, m.id, reason="ok")
    # Caller opts out → mutation node remains stale.
    counts = graph.update_from_sqlite(sqlite_conn, include_mutations=False)
    assert "Mutation" not in counts
    status = graph.query(
        "MATCH (m:Mutation {id: $i}) RETURN m.status",
        params={"i": int(m.id)},
    ).rows[0][0]
    assert status == "pending"  # not refreshed
