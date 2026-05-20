"""v4.68 (ADR 0087) — contract test for the hotSignatures TS SQL.

The dashboard widget's `hotSignatures()` reader in
``control-plane/lib/db.ts`` runs against the same SQLite shape the
Python ``chimera.core.escalation.hot_signatures()`` helper queries.
This test mirrors the TS CTE in Python and asserts the aggregates
match — so a task_escalations schema change that breaks the
dashboard widget also breaks pytest.

Mirror file: control-plane/lib/db.ts:hotSignatures
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import _signature, record_failure
from chimera.memory import open_and_init


# Verbatim mirror of the SQL inside hotSignatures (control-plane/lib/db.ts).
HOT_SIGNATURES_SQL = (
    "SELECT signature, "
    "  COUNT(*) AS total_failures, "
    "  GROUP_CONCAT(DISTINCT tier) AS tiers, "
    "  MIN(cycle) AS first_cycle, "
    "  MAX(cycle) AS last_cycle "
    "FROM task_escalations "
    "GROUP BY signature "
    "HAVING total_failures >= ? "
    "ORDER BY total_failures DESC, last_cycle DESC "
    "LIMIT ?"
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_empty_table_returns_zero_rows(db):
    rows = db.execute(HOT_SIGNATURES_SQL, (2, 10)).fetchall()
    assert list(rows) == []


def test_threshold_filters_low_count_signatures(db):
    """One signature with 1 failure should NOT appear at threshold=2."""
    record_failure(db, task_text="single failure here", tier="haiku",
                   finish_reason="max_rounds", rounds_used=20, cycle=1)
    rows = db.execute(HOT_SIGNATURES_SQL, (2, 10)).fetchall()
    assert list(rows) == []
    # threshold=1 → it appears.
    rows = db.execute(HOT_SIGNATURES_SQL, (1, 10)).fetchall()
    assert len(rows) == 1
    assert rows[0]["total_failures"] == 1


def test_groups_by_signature(db):
    """Same task_text → same signature → grouped."""
    text = "the same task text used twice"
    record_failure(db, task_text=text, tier="haiku",
                   finish_reason="max_rounds", rounds_used=20, cycle=1)
    record_failure(db, task_text=text, tier="sonnet",
                   finish_reason="artifact_missing", rounds_used=15, cycle=2)
    rows = db.execute(HOT_SIGNATURES_SQL, (2, 10)).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["signature"] == _signature(text)
    assert r["total_failures"] == 2
    assert r["first_cycle"] == 1
    assert r["last_cycle"] == 2
    # tiers field is GROUP_CONCAT (comma-separated, order not guaranteed
    # — the widget splits and re-displays).
    tiers = set((r["tiers"] or "").split(","))
    assert tiers == {"haiku", "sonnet"}


def test_orders_by_total_failures_desc(db):
    """Two signatures: A with 3 failures, B with 2. A should come first."""
    text_a = "task A with many failures"
    text_b = "task B with fewer failures"
    for cycle in (1, 2, 3):
        record_failure(db, task_text=text_a, tier="haiku",
                       finish_reason="max_rounds", rounds_used=20, cycle=cycle)
    for cycle in (4, 5):
        record_failure(db, task_text=text_b, tier="sonnet",
                       finish_reason="max_rounds", rounds_used=15, cycle=cycle)
    rows = db.execute(HOT_SIGNATURES_SQL, (2, 10)).fetchall()
    assert len(rows) == 2
    assert rows[0]["total_failures"] == 3
    assert rows[0]["signature"] == _signature(text_a)
    assert rows[1]["total_failures"] == 2
    assert rows[1]["signature"] == _signature(text_b)


def test_limit_caps_result(db):
    """5 distinct signatures, limit=2 → returns 2."""
    for i in range(5):
        # Make each task text produce a distinct signature by using
        # different ≥4-char tokens.
        text = f"distinct alpha bravo task signature variant {i:04d}xxxx"
        for cycle in (1, 2):
            record_failure(db, task_text=text, tier="haiku",
                           finish_reason="max_rounds", rounds_used=20,
                           cycle=cycle)
    rows = db.execute(HOT_SIGNATURES_SQL, (2, 2)).fetchall()
    assert len(rows) == 2
