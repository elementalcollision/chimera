"""v4.51 — contract test for the modelUtilization SQL.

The aggregation lives in `control-plane/lib/db.ts` (TypeScript), but
the SQL itself runs against the same SQLite shape Python writes. This
test mirrors the CTE in Python and asserts the aggregates so a schema
change in `api_calls` that breaks the dashboard query also breaks
pytest.

If you change the SQL in lib/db.ts, mirror it here.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# Verbatim mirror of the TS query in control-plane/lib/db.ts (modelUtilization).
# v4.57 fix (ADR 0076 §"Timestamp normalization"): wrap created_at in
# datetime() on both sides so the ISO-T-separator format that
# record_api_call writes string-compares correctly against SQLite's
# datetime('now', ...) output (which uses space separator + no tz).
# Raw string compare put 'T' (84) > space (32) at position 10, so
# old rows leaked into the window. Mirrors the fix in control-plane/lib/db.ts.
MODEL_UTILIZATION_SQL = (
    "WITH per_cycle AS ( "
    "  SELECT model_id, cycle, COUNT(*) AS n "
    "  FROM api_calls GROUP BY model_id, cycle "
    ") "
    "SELECT a.model_id, "
    "  COUNT(*) AS total, "
    "  SUM(CASE WHEN datetime(a.created_at) >= datetime('now', '-1 day')  THEN 1 ELSE 0 END) AS last_24h, "
    "  SUM(CASE WHEN datetime(a.created_at) >= datetime('now', '-1 hour') THEN 1 ELSE 0 END) AS last_hour, "
    "  COALESCE((SELECT MAX(n) FROM per_cycle p WHERE p.model_id = a.model_id), 0) AS peak_per_cycle "
    "FROM api_calls a "
    "GROUP BY a.model_id "
    "ORDER BY total DESC "
    "LIMIT ?"
)


def _seed(db, model_id: str, cycle: int, n: int) -> None:
    for _ in range(n):
        record_api_call(
            db, cycle=cycle, provider="fake", model_id=model_id,
            input_tokens=100, output_tokens=50, finish_reason="stop",
        )


def test_model_utilization_aggregates_correctly(db):
    _seed(db, "deepseek/deepseek-v4-flash", cycle=1, n=10)
    _seed(db, "deepseek/deepseek-v4-flash", cycle=2, n=235)
    _seed(db, "anthropic/claude-opus-4-7", cycle=2, n=3)

    rows = list(db.execute(MODEL_UTILIZATION_SQL, (10,)))
    rows_by_model = {r["model_id"]: r for r in rows}

    flash = rows_by_model["deepseek/deepseek-v4-flash"]
    assert flash["total"] == 245
    assert flash["peak_per_cycle"] == 235  # the cycle-2 hot spell

    opus = rows_by_model["anthropic/claude-opus-4-7"]
    assert opus["total"] == 3
    assert opus["peak_per_cycle"] == 3


def test_model_utilization_orders_by_total_desc(db):
    _seed(db, "model-a", cycle=1, n=5)
    _seed(db, "model-b", cycle=1, n=15)
    _seed(db, "model-c", cycle=1, n=10)
    rows = list(db.execute(MODEL_UTILIZATION_SQL, (10,)))
    assert [r["model_id"] for r in rows] == ["model-b", "model-c", "model-a"]


def test_model_utilization_limit_truncates(db):
    for i in range(8):
        _seed(db, f"model-{i}", cycle=1, n=i + 1)
    rows = list(db.execute(MODEL_UTILIZATION_SQL, (3,)))
    assert len(rows) == 3
    # Highest-total three: model-7 (8 calls), model-6 (7), model-5 (6).
    assert [r["model_id"] for r in rows] == ["model-7", "model-6", "model-5"]


def test_model_utilization_last_hour_uses_created_at(db):
    """Rows from now should land in last_hour; older rows should not."""
    _seed(db, "fresh", cycle=1, n=2)
    # Backdate one row to 2 hours ago.
    db.execute(
        "INSERT INTO api_calls (cycle, provider, model_id, finish_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "fake", "stale", "stop",
         (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2))
         .isoformat(timespec="seconds")),
    )
    rows = {r["model_id"]: r for r in db.execute(MODEL_UTILIZATION_SQL, (10,))}
    assert rows["fresh"]["last_hour"] == 2
    assert rows["stale"]["last_hour"] == 0
    assert rows["stale"]["last_24h"] == 1  # within 24h though


def test_model_utilization_empty_db(db):
    rows = list(db.execute(MODEL_UTILIZATION_SQL, (10,)))
    assert rows == []
