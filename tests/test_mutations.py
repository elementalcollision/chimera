"""Tests for the mutation queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    approve_mutation,
    bump_recurrence,
    create_mutation,
    get_mutation,
    list_mutations,
    mark_applied,
    mark_failed,
    open_and_init,
    queue_health,
    reject_mutation,
    sweep_stale,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_create_mutation_starts_pending(db):
    m = create_mutation(
        db, type="skill_proposal", payload={"name": "sum", "description": "add two ints"}
    )
    assert m.status == "pending"
    assert m.payload["name"] == "sum"
    assert m.id > 0


def test_get_mutation_roundtrip(db):
    m = create_mutation(db, type="config_change", payload={"k": "v"})
    again = get_mutation(db, m.id)
    assert again is not None
    assert again.id == m.id
    assert again.payload == {"k": "v"}


def test_list_mutations_filters_by_status_and_type(db):
    create_mutation(db, type="skill_proposal", payload={"a": 1})
    m2 = create_mutation(db, type="config_change", payload={"b": 2})
    create_mutation(db, type="skill_proposal", payload={"c": 3})
    reject_mutation(db, m2.id, reason="not needed")

    skills = list_mutations(db, type="skill_proposal")
    assert len(skills) == 2

    rejected = list_mutations(db, status="rejected")
    assert len(rejected) == 1
    assert rejected[0].type == "config_change"

    pending = list_mutations(db, status="pending")
    assert len(pending) == 2


def test_approve_then_apply_advances_state(db):
    m = create_mutation(db, type="skill_proposal", payload={"name": "echo"})
    approved = approve_mutation(db, m.id, reason="looks good")
    assert approved.status == "approved"
    assert approved.approved_at is not None
    applied = mark_applied(db, m.id, reason="activated as chimera.tools.dynamic.echo")
    assert applied.status == "applied"
    assert applied.applied_at is not None


def test_reject_pending_mutation(db):
    m = create_mutation(db, type="skill_proposal", payload={"name": "bad"})
    rejected = reject_mutation(db, m.id, reason="violates safety")
    assert rejected.status == "rejected"
    assert rejected.reason == "violates safety"


def test_reject_already_approved_raises(db):
    m = create_mutation(db, type="skill_proposal", payload={})
    approve_mutation(db, m.id)
    with pytest.raises(ValueError):
        reject_mutation(db, m.id)


def test_approve_unknown_mutation_raises(db):
    with pytest.raises(ValueError):
        approve_mutation(db, 9999)


def test_mark_failed_records_reason(db):
    m = create_mutation(db, type="skill_proposal", payload={})
    approve_mutation(db, m.id)
    failed = mark_failed(db, m.id, reason="sandbox validation failed")
    assert failed.status == "failed"
    assert failed.reason == "sandbox validation failed"


def test_sweep_stale_expires_old_pending(db, monkeypatch):
    import datetime as dt

    import chimera.memory.mutations as mod

    # Insert one pending mutation with an artificially old timestamp.
    old_iso = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    ).isoformat(timespec="seconds")
    monkeypatch.setattr(mod, "_utc_now_iso", lambda: old_iso)
    create_mutation(db, type="skill_proposal", payload={})
    # Reset to real now.
    monkeypatch.undo()
    # Sweep with a tight window (12 cycles * 15min = 3 hours).
    n = sweep_stale(db, older_than_cycles=12, current_cycle=20)
    assert n == 1
    expired = list_mutations(db, status="expired")
    assert len(expired) == 1


# ── v4.19: recurrence + queue health ────────────────────────


def test_bump_recurrence_increments_in_place(db):
    m = create_mutation(db, type="skill_proposal", payload={"name": "x"})
    assert m.recurrence_count == 0
    bumped = bump_recurrence(db, m.id)
    assert bumped is not None
    assert bumped.recurrence_count == 1
    again = bump_recurrence(db, m.id)
    assert again.recurrence_count == 2
    # And no new rows were enqueued.
    assert len(list_mutations(db)) == 1


def test_bump_recurrence_missing_id_returns_none(db):
    assert bump_recurrence(db, 9999) is None


def test_queue_health_empty(db):
    snap = queue_health(db)
    assert snap["counts"] == {}
    assert snap["pending_oldest_age_seconds"] is None
    assert snap["pending_recurrence_max"] == 0
    assert snap["pending_recurrence_total"] == 0
    assert snap["approved_ratio"] is None


def test_queue_health_mixed(db):
    a = create_mutation(db, type="skill_proposal", payload={"name": "a"})
    b = create_mutation(db, type="skill_proposal", payload={"name": "b"})
    c = create_mutation(db, type="config_change", payload={"k": "v"})
    bump_recurrence(db, a.id)
    bump_recurrence(db, a.id)
    bump_recurrence(db, b.id)
    approve_mutation(db, c.id)
    mark_applied(db, c.id)
    # one rejected for the ratio denominator
    d = create_mutation(db, type="skill_proposal", payload={"name": "d"})
    reject_mutation(db, d.id)

    snap = queue_health(db)
    assert snap["counts"]["pending"] == 2  # a + b
    assert snap["counts"]["applied"] == 1
    assert snap["counts"]["rejected"] == 1
    assert snap["pending_recurrence_max"] == 2  # a was bumped twice
    assert snap["pending_recurrence_total"] == 3  # 2 + 1
    # applied=1 over decided (applied + rejected) = 2 → 0.5
    assert snap["approved_ratio"] == pytest.approx(0.5)
    assert snap["pending_oldest_age_seconds"] is not None
    assert snap["pending_oldest_age_seconds"] >= 0


def test_adaptation_already_proposed_bumps_existing(tmp_path: Path, db):
    """End-to-end: maybe_propose_synthesis_skill should bump, not duplicate."""
    from chimera.core.adaptation import (
        maybe_propose_synthesis_skill,
        record_fragmentation,
    )

    log_path = tmp_path / "frag.jsonl"
    task = "write a unified report summarising sources A, B, C into `state/out.md`"
    # Two fragmentation records → above default threshold of 2.
    for _ in range(2):
        record_fragmentation(
            cycle=1,
            task_text=task,
            rounds_used=12,
            tool_call_count=10,
            missing_artifacts=["state/out.md"],
            path=log_path,
        )

    first = maybe_propose_synthesis_skill(
        db, cycle=2, task_text=task,
        missing_artifacts=["state/out.md"], path=log_path,
    )
    assert first is not None
    # Same signature → bump, no new row.
    second = maybe_propose_synthesis_skill(
        db, cycle=3, task_text=task,
        missing_artifacts=["state/out.md"], path=log_path,
    )
    assert second == first
    rows = list_mutations(db, type="skill_proposal")
    assert len(rows) == 1
    assert rows[0].recurrence_count == 1
