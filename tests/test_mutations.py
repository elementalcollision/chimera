"""Tests for the mutation queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    approve_mutation,
    create_mutation,
    get_mutation,
    list_mutations,
    mark_applied,
    mark_failed,
    open_and_init,
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
