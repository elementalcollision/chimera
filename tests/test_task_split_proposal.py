"""v4.65 (ADR 0084) — auto-loop integration for the task splitter."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import record_failure
from chimera.core.task_split_proposal import (
    apply_task_split,
    propose_task_split,
    should_propose_split_for,
    task_split_enabled,
)
from chimera.memory import open_and_init
from chimera.memory.mutations import (
    approve_mutation,
    get_mutation,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _write_inbox(p: Path, lines: list[str]) -> Path:
    p.write_text("# Inbox\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


# ── env gate ──────────────────────────────────────────────────────


def test_default_off(monkeypatch):
    monkeypatch.delenv("CHIMERA_TASK_SPLITTER_ENABLED", raising=False)
    assert task_split_enabled() is False


def test_truthy_values_enable(monkeypatch):
    for v in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("CHIMERA_TASK_SPLITTER_ENABLED", v)
        assert task_split_enabled() is True


def test_falsy_values_disable(monkeypatch):
    for v in ("0", "false", "no", "", "anything-else"):
        monkeypatch.setenv("CHIMERA_TASK_SPLITTER_ENABLED", v)
        assert task_split_enabled() is False


# ── should_propose_split_for ──────────────────────────────────────


def _splittable_task() -> str:
    """A task text that trips is_splittable_shape with confidence ≥ 0.5."""
    return (
        "Research and write the FOUR sections (1) capital (2) feedback "
        "(3) antagonists (4) omissions, each with peer-reviewed citations."
    )


def test_should_not_propose_for_unsplittable_text(db):
    """Simple one-step text doesn't trip the heuristic."""
    assert should_propose_split_for(db, "Refactor the loop body") is False


def test_should_not_propose_without_enough_failures(db):
    """Heuristic alone is not enough — need ≥3 prior failures."""
    text = _splittable_task()
    # 2 failures < min_failures=3 → don't propose yet.
    record_failure(db, task_text=text, tier="haiku", finish_reason="max_rounds",
                   rounds_used=20, cycle=1)
    record_failure(db, task_text=text, tier="sonnet", finish_reason="max_rounds",
                   rounds_used=20, cycle=2)
    assert should_propose_split_for(db, text) is False


def test_should_propose_when_heuristic_and_failures_align(db):
    """Three failures + splittable shape → propose."""
    text = _splittable_task()
    for cycle in (1, 2, 3):
        record_failure(db, task_text=text, tier="haiku",
                       finish_reason="max_rounds", rounds_used=20, cycle=cycle)
    assert should_propose_split_for(db, text) is True


def test_should_not_re_propose_when_already_pending(db):
    """If a task_split mutation already exists for this signature,
    don't propose again — even if the conditions are still met."""
    text = _splittable_task()
    for cycle in (1, 2, 3):
        record_failure(db, task_text=text, tier="haiku",
                       finish_reason="max_rounds", rounds_used=20, cycle=cycle)
    propose_task_split(db, text, subtasks=["sub a", "sub b", "sub c"])
    # Now the signature has a pending mutation; should not re-propose.
    assert should_propose_split_for(db, text) is False


# ── propose_task_split ────────────────────────────────────────────


def test_propose_creates_pending_mutation(db):
    text = _splittable_task()
    mid = propose_task_split(db, text, subtasks=["a", "b", "c"])
    assert mid is not None
    m = get_mutation(db, mid)
    assert m is not None
    assert m.type == "task_split"
    assert m.status == "pending"
    assert m.payload["subtasks"] == ["a", "b", "c"]
    assert m.payload["original_task"] == text
    assert m.payload["signature"]


def test_propose_empty_subtasks_returns_none(db):
    assert propose_task_split(db, "anything", subtasks=[]) is None


# ── apply_task_split ──────────────────────────────────────────────


def test_apply_rewrites_inbox(tmp_path: Path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] Simple unrelated task",
        "- [ ] Research and write the FOUR sections — bundled, failing",
        "- [ ] Another task",
    ])
    text = "Research and write the FOUR sections — bundled, failing"
    mid = propose_task_split(db, text, subtasks=[
        "Research section 1",
        "Research section 2",
        "Research section 3",
        "Research section 4",
    ])
    approve_mutation(db, mid)
    result = apply_task_split(db, mid, inbox)
    assert result["ok"], result
    body = inbox.read_text(encoding="utf-8")
    # Original line is marked `[-]` with the split annotation.
    assert "[-] Research and write the FOUR sections" in body
    assert "SPLIT v4.65" in body
    # Sub-tasks appear as new `[ ]` lines.
    for sub in (
        "Research section 1", "Research section 2",
        "Research section 3", "Research section 4",
    ):
        assert f"- [ ] {sub}" in body
    # Unrelated tasks survive untouched.
    assert "- [ ] Simple unrelated task" in body
    assert "- [ ] Another task" in body
    # Mutation status flips to applied.
    m = get_mutation(db, mid)
    assert m.status == "applied"


def test_apply_idempotent_for_already_applied(tmp_path: Path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] The task with FOUR sections",
    ])
    mid = propose_task_split(
        db, "The task with FOUR sections", subtasks=["a", "b"],
    )
    approve_mutation(db, mid)
    apply_task_split(db, mid, inbox)
    # Second call is a no-op (returns ok + already-applied reason).
    result = apply_task_split(db, mid, inbox)
    assert result["ok"]
    assert "already applied" in result["reason"]


def test_apply_refuses_unapproved_mutation(tmp_path: Path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] Pending task with FOUR sections",
    ])
    mid = propose_task_split(
        db, "Pending task with FOUR sections", subtasks=["a", "b"],
    )
    # Skip approve.
    result = apply_task_split(db, mid, inbox)
    assert result["ok"] is False
    assert "must be approved" in result["reason"]


def test_apply_handles_missing_original_task(tmp_path: Path, db):
    """If the operator edited INBOX after the mutation was queued,
    apply should fail gracefully and mark the mutation as failed."""
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] A completely different task",
    ])
    mid = propose_task_split(
        db, "The task that's no longer in INBOX with FOUR sections",
        subtasks=["a", "b"],
    )
    approve_mutation(db, mid)
    result = apply_task_split(db, mid, inbox)
    assert result["ok"] is False
    assert "not found" in result["reason"]
    m = get_mutation(db, mid)
    assert m.status == "failed"


def test_apply_refuses_non_task_split_mutation(db, tmp_path):
    """Defensive: feeding a kill_entity mutation through the
    task_split applier should refuse, not corrupt anything."""
    from chimera.memory.mutations import create_mutation
    m = create_mutation(
        db, type="kill_entity",
        payload={"entity_id": "ent_123", "kind": "skill", "name": "x"},
    )
    db.commit()
    approve_mutation(db, m.id)
    inbox = _write_inbox(tmp_path / "INBOX.md", ["- [ ] anything"])
    result = apply_task_split(db, m.id, inbox)
    assert result["ok"] is False
    assert "expected task_split" in result["reason"]
