"""v4.54 (ADR 0073) — hot-signature alarm.

Signatures with ≥ N failures get surfaced to the operator as part of
`chimera escalations summary`. The postmortem heuristic is: 2 hits on
the same signature is the inflection point where "tier was wrong"
tips into "task text needs rewriting." This test pins the detection,
the threshold default, sort order, and excerpt behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import hot_signatures, record_failure
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _fail(db, *, task_text: str, tier: str, cycle: int, finish_reason: str = "max_rounds"):
    """Helper: record a failure with the given parameters."""
    record_failure(
        db, task_text=task_text, tier=tier, finish_reason=finish_reason,
        rounds_used=22, cycle=cycle,
    )


def test_empty_table_returns_empty(db):
    assert hot_signatures(db) == []


def test_single_failure_not_hot(db):
    _fail(db, task_text="Research the four missing sections of the paper", tier="haiku", cycle=15)
    assert hot_signatures(db, threshold=2) == []


def test_two_failures_on_same_signature_is_hot(db):
    # Same task text → same signature → counts as 2 failures.
    _fail(db, task_text="Research the four missing sections of the paper", tier="haiku", cycle=15)
    _fail(db, task_text="Research the four missing sections of the paper", tier="sonnet", cycle=18)
    hot = hot_signatures(db, threshold=2)
    assert len(hot) == 1
    h = hot[0]
    assert h.total_failures == 2
    assert "haiku" in h.tiers and "sonnet" in h.tiers
    assert h.first_seen_cycle == 15
    assert h.last_seen_cycle == 18


def test_sort_by_total_failures_desc(db):
    # Signature A: 3 failures. Signature B: 2 failures.
    for c in (1, 2, 3):
        _fail(db, task_text="task A — heavy fanout research with many sub-agents", tier="haiku", cycle=c)
    for c in (4, 5):
        _fail(db, task_text="task B — different shape that fails twice", tier="sonnet", cycle=c)
    hot = hot_signatures(db, threshold=2)
    assert len(hot) == 2
    assert hot[0].total_failures == 3  # A first
    assert hot[1].total_failures == 2  # B second


def test_threshold_parameter(db):
    _fail(db, task_text="task with one failure", tier="haiku", cycle=1)
    _fail(db, task_text="task with two failures", tier="haiku", cycle=2)
    _fail(db, task_text="task with two failures", tier="haiku", cycle=3)
    # threshold=1 surfaces both; threshold=2 only the second.
    assert len(hot_signatures(db, threshold=1)) == 2
    assert len(hot_signatures(db, threshold=2)) == 1
    assert len(hot_signatures(db, threshold=5)) == 0


def test_excerpt_truncated_to_120_chars(db):
    long_text = "x" * 500 + " end-of-text-marker"
    _fail(db, task_text=long_text, tier="haiku", cycle=1)
    _fail(db, task_text=long_text, tier="haiku", cycle=2)
    hot = hot_signatures(db, threshold=2)
    assert len(hot) == 1
    assert len(hot[0].excerpt) <= 120


def test_excerpt_strips_newlines(db):
    text = "Line one\nLine two\nLine three with detail"
    _fail(db, task_text=text, tier="haiku", cycle=1)
    _fail(db, task_text=text, tier="haiku", cycle=2)
    hot = hot_signatures(db, threshold=2)
    assert "\n" not in hot[0].excerpt


def test_last_finish_reason_is_most_recent(db):
    _fail(db, task_text="recurrent task that fails differently each time",
          tier="haiku", cycle=1, finish_reason="max_rounds")
    _fail(db, task_text="recurrent task that fails differently each time",
          tier="sonnet", cycle=2, finish_reason="artifact_missing")
    hot = hot_signatures(db, threshold=2)
    assert hot[0].last_finish_reason == "artifact_missing"


def test_schema_missing_returns_empty(tmp_path):
    # Empty SQLite file with no schema → hot_signatures should not raise
    import sqlite3
    db = sqlite3.connect(tmp_path / "empty.db")
    db.row_factory = sqlite3.Row
    try:
        assert hot_signatures(db) == []
    finally:
        db.close()


def test_overnight_burn_signature_would_be_caught(db):
    """The 2026-05-19 burn was 5+ cycles on the dashboard-honesty task.
    Once v4.46 escalation memory recorded the first 2 of those, this
    alarm would have fired. Pin that."""
    burn_text = "Dashboard honesty audit — spawn 14 sub-agents and compile"
    for cycle in (17, 18, 19, 20, 21):
        _fail(db, task_text=burn_text,
              tier=("haiku" if cycle < 18 else "sonnet" if cycle < 20 else "opus"),
              cycle=cycle)
    hot = hot_signatures(db, threshold=2)
    assert len(hot) == 1
    assert hot[0].total_failures == 5
    assert "opus" in hot[0].tiers
