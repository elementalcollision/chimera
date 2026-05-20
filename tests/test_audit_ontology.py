"""v4.21 — memory / ontology audit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    apply_approved_kills,
    approve_mutation,
    audit_ontology,
    auto_archive_stale_deprecated,
    create_entity,
    get_entity,
    list_mutations,
    open_and_init,
    propose_kill_archived,
    reanchor_history,
    record_activity,
    transition_entity,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_audit_empty_db(db):
    snap = audit_ontology(db, current_cycle=5)
    assert snap["total_entities"] == 0
    assert snap["by_kind"] == {}
    assert snap["by_state"] == {}
    assert snap["stale_count"] == 0
    assert snap["dead_count"] == 0
    assert snap["reanchor_events_in_window"] == 0


def test_audit_flags_stale_entity(db):
    # Create an entity in cycle 1; audit at cycle 30 → 29 cycles in state.
    e = create_entity(db, kind="plan", name="ancient", cycle=1)
    # Activity within the window so it's not also flagged "dead".
    record_activity(
        db, cycle=28, cell_id="x", agent_id="chimera",
        activity_type="touch", layer="memory", cell_ref=e.id,
    )

    snap = audit_ontology(db, current_cycle=30, stale_after_cycles=20)
    assert snap["stale_count"] == 1
    [stale] = snap["stale_entities"]
    assert stale["id"] == e.id
    assert stale["kfm_state"] == "NEW"
    assert stale["cycles_in_state"] == 29


def test_audit_flags_dead_entity(db):
    # Entity created at cycle 1, no activity ever, audit at cycle 30.
    e = create_entity(db, kind="skill", name="ghost", cycle=1)

    snap = audit_ontology(
        db, current_cycle=30, activity_window_cycles=10,
    )
    ids = [d["id"] for d in snap["dead_entities"]]
    assert e.id in ids


# v4.64 (ADR 0083) — these tests pin the new transition-based "dead"
# semantic. Prior to v4.64 the audit joined dead_entities on
# agent_activity_log.cell_ref, which was never populated in production,
# so every non-terminal entity showed as dead. Now the join is against
# entity_transitions.entity_id.


def test_dead_excludes_recently_transitioned_entity(db):
    """An entity with a transition INSIDE the window is alive."""
    e = create_entity(db, kind="skill", name="alive", cycle=1)
    # Transition at cycle 25 — well inside the 10-cycle window from
    # cycle=30.
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=25)
    snap = audit_ontology(
        db, current_cycle=30, activity_window_cycles=10,
    )
    ids = [d["id"] for d in snap["dead_entities"]]
    assert e.id not in ids
    # Sanity: count should reflect this.
    assert snap["dead_count"] == 0


def test_dead_flags_entity_with_only_old_transitions(db):
    """An entity whose transitions all predate the window IS dead."""
    e = create_entity(db, kind="skill", name="old-mover", cycle=1)
    # Single old transition.
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=5)
    # Audit at cycle 30 with a 10-cycle window → cutoff = 20 → the
    # cycle=5 transition is outside.
    snap = audit_ontology(
        db, current_cycle=30, activity_window_cycles=10,
    )
    ids = [d["id"] for d in snap["dead_entities"]]
    assert e.id in ids


def test_dead_does_not_misreport_under_old_cell_ref_bug(db):
    """Regression: pre-v4.64, every non-terminal entity showed as
    dead because nothing wrote cell_ref. Verify that an entity with
    a current-cycle transition is NOT in dead_entities now."""
    e = create_entity(db, kind="plan", name="current", cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    snap = audit_ontology(
        db, current_cycle=5, activity_window_cycles=10,
    )
    ids = [d["id"] for d in snap["dead_entities"]]
    assert e.id not in ids


def test_audit_skips_terminal_states(db):
    # Walk an entity through to ARCHIVED — it should NOT count as stale.
    e = create_entity(db, kind="plan", name="retired", cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    transition_entity(db, e.id, "STABLE", "m", cycle=4)
    transition_entity(db, e.id, "DEPRECATED", "k", cycle=5)
    transition_entity(db, e.id, "ARCHIVED", "k", cycle=6)
    snap = audit_ontology(db, current_cycle=100, stale_after_cycles=10)
    assert snap["stale_count"] == 0
    assert snap["dead_count"] == 0


def test_audit_counts_reanchor_events(db):
    # Two plans walked through STABLE → DEPRECATED via the K-operator.
    for i, cyc in enumerate([5, 12]):
        e = create_entity(db, kind="plan", name=f"plan_{i}", cycle=1)
        transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
        transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
        transition_entity(db, e.id, "STABLE", "m", cycle=4)
        transition_entity(db, e.id, "DEPRECATED", "k", cycle=cyc)

    snap = audit_ontology(db, current_cycle=20, reanchor_window_cycles=50)
    assert snap["reanchor_events_in_window"] == 2
    # And both entities are now in DEPRECATED — deprecated_unarchived == 2.
    assert snap["deprecated_unarchived"] == 2


def test_audit_by_kind_and_state(db):
    create_entity(db, kind="plan", name="p1", cycle=1)
    create_entity(db, kind="skill", name="s1", cycle=1)
    create_entity(db, kind="skill", name="s2", cycle=1)
    snap = audit_ontology(db, current_cycle=2)
    assert snap["by_kind"]["plan"] == 1
    assert snap["by_kind"]["skill"] == 2
    assert snap["by_state"]["NEW"] == 3


# ── v4.24: auto-archive ──────────────────────────────────────


def _walk_to_deprecated(db, name: str, deprecate_cycle: int):
    """Helper: create an entity and walk it to DEPRECATED."""
    e = create_entity(db, kind="plan", name=name, cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    transition_entity(db, e.id, "STABLE", "m", cycle=4)
    transition_entity(db, e.id, "DEPRECATED", "k", cycle=deprecate_cycle)
    return e


def test_auto_archive_promotes_stale_deprecated(db):
    e = _walk_to_deprecated(db, "old_plan", deprecate_cycle=5)
    # 50 cycles later, threshold is 30 → should archive.
    archived = auto_archive_stale_deprecated(
        db, current_cycle=55, archive_after_cycles=30,
    )
    assert len(archived) == 1
    assert archived[0]["id"] == e.id
    assert archived[0]["cycles_in_state"] == 50
    fresh = get_entity(db, e.id)
    assert fresh is not None
    assert fresh.kfm_state == "ARCHIVED"
    assert fresh.state_entered_at_cycle == 55


def test_auto_archive_skips_recent_deprecated(db):
    _walk_to_deprecated(db, "fresh_plan", deprecate_cycle=50)
    # Only 5 cycles in DEPRECATED — under the threshold.
    archived = auto_archive_stale_deprecated(
        db, current_cycle=55, archive_after_cycles=30,
    )
    assert archived == []


def test_auto_archive_dry_run_does_not_transition(db):
    e = _walk_to_deprecated(db, "to_archive", deprecate_cycle=5)
    archived = auto_archive_stale_deprecated(
        db, current_cycle=100, archive_after_cycles=30, dry_run=True,
    )
    assert len(archived) == 1
    fresh = get_entity(db, e.id)
    assert fresh is not None
    assert fresh.kfm_state == "DEPRECATED"  # unchanged


def test_auto_archive_max_per_cycle_caps_work(db):
    for i in range(5):
        _walk_to_deprecated(db, f"p_{i}", deprecate_cycle=5)
    archived = auto_archive_stale_deprecated(
        db, current_cycle=100, archive_after_cycles=30, max_per_cycle=3,
    )
    assert len(archived) == 3
    # Two are still DEPRECATED, waiting for next cycle.
    snap = audit_ontology(db, current_cycle=100)
    assert snap["by_state"].get("DEPRECATED") == 2
    assert snap["by_state"].get("ARCHIVED") == 3


def test_auto_archive_ignores_non_deprecated(db):
    # STABLE entity, even very old → ignored.
    e = create_entity(db, kind="plan", name="ancient_stable", cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    transition_entity(db, e.id, "STABLE", "m", cycle=4)
    archived = auto_archive_stale_deprecated(
        db, current_cycle=999, archive_after_cycles=30,
    )
    assert archived == []


# ── v4.30: reanchor_history ──────────────────────────────────


def test_reanchor_history_empty(db):
    buckets = reanchor_history(db, current_cycle=50, bucket_size=10, n_buckets=5)
    assert len(buckets) == 5
    assert all(b["count"] == 0 for b in buckets)
    # Buckets are oldest-first and contiguous.
    for prev, cur in zip(buckets, buckets[1:]):
        assert prev["end_cycle"] == cur["start_cycle"]


def test_reanchor_history_buckets_demotions_correctly(db):
    # Six K-operator demotions across cycles 5, 12, 13, 21, 33, 47.
    for i, cyc in enumerate([5, 12, 13, 21, 33, 47]):
        e = _walk_to_deprecated(db, f"plan_{i}", deprecate_cycle=cyc)
        _ = e  # noqa: F841 — _walk_to_deprecated creates the row we want

    # At cycle 50, bucket_size=10, n_buckets=5 → spans cycles 1..50.
    buckets = reanchor_history(db, current_cycle=50, bucket_size=10, n_buckets=5)
    counts = [b["count"] for b in buckets]
    # Buckets: [1,11)=1 (cyc 5), [11,21)=2 (12+13), [21,31)=1 (21),
    # [31,41)=1 (33), [41,51)=1 (47)
    assert counts == [1, 2, 1, 1, 1]
    # Sum matches total entities demoted.
    assert sum(counts) == 6


def test_reanchor_history_ignores_non_k_transitions(db):
    # M-operator promotion of an entity through to STABLE — not counted.
    e = create_entity(db, kind="plan", name="m_only", cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    transition_entity(db, e.id, "STABLE", "m", cycle=4)
    # No K-operator demotion → all buckets zero.
    buckets = reanchor_history(db, current_cycle=20, bucket_size=5, n_buckets=4)
    assert sum(b["count"] for b in buckets) == 0


def test_reanchor_history_degenerate_inputs(db):
    assert reanchor_history(db, current_cycle=10, bucket_size=0) == []
    assert reanchor_history(db, current_cycle=10, n_buckets=0) == []


# ── v4.39: kill-archived operator workflow ───────────────────


def _walk_to_archived(db, name: str, *, archive_cycle: int):
    """Helper: create an entity and walk it all the way to ARCHIVED."""
    e = create_entity(db, kind="plan", name=name, cycle=1)
    transition_entity(db, e.id, "EXPERIMENTAL", "f", cycle=2)
    transition_entity(db, e.id, "CANDIDATE", "m", cycle=3)
    transition_entity(db, e.id, "STABLE", "m", cycle=4)
    transition_entity(db, e.id, "DEPRECATED", "k", cycle=5)
    transition_entity(db, e.id, "ARCHIVED", "k", cycle=archive_cycle)
    return e


def test_propose_kill_queues_pending_mutation(db):
    e = _walk_to_archived(db, "ancient", archive_cycle=10)
    proposed = propose_kill_archived(
        db, current_cycle=110, archive_after_cycles=90,
    )
    assert len(proposed) == 1
    assert proposed[0]["id"] == e.id
    muts = list_mutations(db, type="kill_entity")
    assert len(muts) == 1
    assert muts[0].status == "pending"
    assert muts[0].payload["entity_id"] == e.id


def test_propose_kill_skips_recent_archived(db):
    _walk_to_archived(db, "recent", archive_cycle=100)
    # Only 10 cycles in ARCHIVED — under default threshold of 90.
    proposed = propose_kill_archived(db, current_cycle=110, archive_after_cycles=90)
    assert proposed == []
    assert list_mutations(db, type="kill_entity") == []


def test_propose_kill_dedups_pending(db):
    _walk_to_archived(db, "p", archive_cycle=10)
    propose_kill_archived(db, current_cycle=110, archive_after_cycles=90)
    # Second call must not queue a duplicate while the first is pending.
    propose_kill_archived(db, current_cycle=120, archive_after_cycles=90)
    muts = list_mutations(db, type="kill_entity")
    assert len(muts) == 1


def test_apply_approved_kills_transitions_to_killed(db):
    e = _walk_to_archived(db, "doomed", archive_cycle=10)
    propose_kill_archived(db, current_cycle=110, archive_after_cycles=90)
    [m] = list_mutations(db, type="kill_entity")
    approve_mutation(db, m.id)

    killed = apply_approved_kills(db, current_cycle=115)
    assert len(killed) == 1
    fresh = get_entity(db, e.id)
    assert fresh is not None
    assert fresh.kfm_state == "KILLED"
    # Mutation is now applied.
    [m_after] = list_mutations(db, type="kill_entity")
    assert m_after.status == "applied"


def test_apply_approved_kills_skips_unapproved(db):
    _walk_to_archived(db, "doomed", archive_cycle=10)
    propose_kill_archived(db, current_cycle=110, archive_after_cycles=90)
    killed = apply_approved_kills(db, current_cycle=115)
    # No approval → no kill.
    assert killed == []
