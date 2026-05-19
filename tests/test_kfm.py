"""Tests for the KFM state machine + SQLite-backed entity store."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.kfm import (
    KFM_STATES,
    LEGAL_TRANSITIONS,
    TRANSITION_AUTHORITY,
    check_transition,
)
from chimera.memory import (
    EntityAlreadyExists,
    EntityNotFound,
    IllegalTransition,
    activity_window,
    create_entity,
    get_entity,
    get_entity_by_name,
    list_entities,
    list_transitions,
    open_and_init,
    record_activity,
    transition_entity,
)


# ── KFM rules (pure) ─────────────────────────────────────────


def test_kfm_states_are_seven_in_order():
    assert KFM_STATES == (
        "NEW",
        "EXPERIMENTAL",
        "CANDIDATE",
        "STABLE",
        "DEPRECATED",
        "ARCHIVED",
        "KILLED",
    )


def test_legal_transitions_cover_all_non_terminal_states():
    for state in KFM_STATES[:-1]:
        assert state in LEGAL_TRANSITIONS
        assert LEGAL_TRANSITIONS[state], f"{state} should have at least one transition"
    assert LEGAL_TRANSITIONS["KILLED"] == frozenset()


def test_authority_table_aligns_with_legal_transitions():
    """Every (from, to) in LEGAL_TRANSITIONS has an authority entry."""
    pairs = {
        (frm, to) for frm, tos in LEGAL_TRANSITIONS.items() for to in tos
    }
    assert pairs == set(TRANSITION_AUTHORITY.keys())


@pytest.mark.parametrize(
    "frm,to,op,ok",
    [
        ("NEW", "EXPERIMENTAL", "f", True),
        ("EXPERIMENTAL", "CANDIDATE", "m", True),
        ("CANDIDATE", "STABLE", "m", True),
        ("STABLE", "DEPRECATED", "k", True),
        ("DEPRECATED", "ARCHIVED", "k", True),
        ("ARCHIVED", "KILLED", "k", True),
        # Wrong operator
        ("NEW", "EXPERIMENTAL", "m", False),
        ("STABLE", "DEPRECATED", "f", False),
        # Illegal transitions
        ("NEW", "STABLE", "f", False),
        ("STABLE", "KILLED", "k", False),
        ("KILLED", "EXPERIMENTAL", "f", False),
        # Unknown states / operators
        ("MIGRATING", "STABLE", "m", False),
        ("STABLE", "FROZEN", "k", False),
        ("NEW", "EXPERIMENTAL", "z", False),
    ],
)
def test_check_transition(frm, to, op, ok):
    result = check_transition(frm, to, op)
    assert result.allowed is ok


def test_bootstrap_bypasses_operator_authority():
    """Bootstrap is the privileged escape for initial entity creation."""
    result = check_transition("NEW", "EXPERIMENTAL", "bootstrap")
    assert result.allowed
    assert result.authorized_operator == "f"


# ── SQLite store + entity CRUD ───────────────────────────────


@pytest.fixture
def conn(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_create_and_get_entity(conn):
    e = create_entity(conn, kind="tool", name="shell", cycle=1)
    assert e.kfm_state == "NEW"
    fetched = get_entity(conn, e.id)
    assert fetched is not None and fetched.name == "shell"
    by_name = get_entity_by_name(conn, kind="tool", name="shell")
    assert by_name is not None and by_name.id == e.id


def test_create_duplicate_raises(conn):
    create_entity(conn, kind="tool", name="shell", cycle=1)
    with pytest.raises(EntityAlreadyExists):
        create_entity(conn, kind="tool", name="shell", cycle=2)


def test_transition_happy_path_advances_state(conn):
    e = create_entity(conn, kind="plan", name="phase-2", cycle=1)
    t = transition_entity(conn, e.id, "EXPERIMENTAL", "f", cycle=2)
    assert t.from_state == "NEW" and t.to_state == "EXPERIMENTAL"
    after = get_entity(conn, e.id)
    assert after.kfm_state == "EXPERIMENTAL"
    assert after.state_entered_at_cycle == 2


def test_transition_illegal_raises_and_does_not_persist(conn):
    e = create_entity(conn, kind="plan", name="phase-2", cycle=1)
    with pytest.raises(IllegalTransition):
        transition_entity(conn, e.id, "STABLE", "m", cycle=2)
    # State unchanged.
    assert get_entity(conn, e.id).kfm_state == "NEW"


def test_transition_wrong_operator_raises(conn):
    e = create_entity(conn, kind="plan", name="phase-2", cycle=1)
    with pytest.raises(IllegalTransition):
        transition_entity(conn, e.id, "EXPERIMENTAL", "m", cycle=2)


def test_transition_unknown_entity_raises(conn):
    with pytest.raises(EntityNotFound):
        transition_entity(conn, "nope", "EXPERIMENTAL", "f", cycle=1)


def test_full_lifecycle_walk(conn):
    """Walk an entity NEW → EXPERIMENTAL → CANDIDATE → STABLE → DEPRECATED → ARCHIVED → KILLED."""
    e = create_entity(conn, kind="tool", name="reader", cycle=1)
    transitions = [
        ("EXPERIMENTAL", "f"),
        ("CANDIDATE", "m"),
        ("STABLE", "m"),
        ("DEPRECATED", "k"),
        ("ARCHIVED", "k"),
        ("KILLED", "k"),
    ]
    for cycle, (to, op) in enumerate(transitions, start=2):
        transition_entity(conn, e.id, to, op, cycle=cycle)
    final = get_entity(conn, e.id)
    assert final.kfm_state == "KILLED"
    audit = list_transitions(conn, e.id)
    assert [t.to_state for t in audit] == [s for s, _ in transitions]


def test_list_entities_filters(conn):
    create_entity(conn, kind="tool", name="a", cycle=1)
    create_entity(conn, kind="tool", name="b", cycle=1)
    create_entity(conn, kind="plan", name="x", cycle=1)
    assert len(list_entities(conn, kind="tool")) == 2
    assert len(list_entities(conn, kind="plan")) == 1
    assert len(list_entities(conn, kfm_state="NEW")) == 3
    assert len(list_entities(conn, kind="tool", kfm_state="STABLE")) == 0


# ── Activity log ─────────────────────────────────────────────


def test_record_activity_idempotent_per_cycle_cell(conn):
    first = record_activity(
        conn, cycle=1, cell_id="A", agent_id="ag", activity_type="tick"
    )
    second = record_activity(
        conn, cycle=1, cell_id="A", agent_id="ag", activity_type="tick"
    )
    assert first is True
    assert second is False


def test_activity_window_summarizes_correctly(conn):
    for cycle in range(1, 6):
        record_activity(
            conn,
            cycle=cycle,
            cell_id=f"cell-{cycle}",
            agent_id="ag",
            activity_type="tick",
            layer="A" if cycle % 2 else "B",
        )
    summary = activity_window(conn, agent_id="ag", current_cycle=5, last_n_cycles=3)
    assert summary["activity_count"] == 3
    assert summary["active_cycles_in_window"] == 3
    assert summary["layer_counts"] == {"A": 2, "B": 1}


def test_ontology_persists_across_reopen(tmp_path: Path):
    db = tmp_path / "chimera.db"
    conn1 = open_and_init(db)
    e = create_entity(conn1, kind="tool", name="reader", cycle=1)
    transition_entity(conn1, e.id, "EXPERIMENTAL", "f", cycle=2)
    conn1.close()
    # Reopen: state survives.
    conn2 = open_and_init(db)
    again = get_entity_by_name(conn2, kind="tool", name="reader")
    assert again is not None
    assert again.kfm_state == "EXPERIMENTAL"
    assert again.state_entered_at_cycle == 2
    conn2.close()
