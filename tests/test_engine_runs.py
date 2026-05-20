"""v4.69 (ADR 0088 §P1) — engine_runs telemetry helpers.

Pins the start/finish lifecycle, the summary aggregator, and the
caller column on api_calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import (
    engine_runs_summary,
    finish_engine_run,
    list_engine_runs,
    open_and_init,
    record_api_call,
    start_engine_run,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── engine_runs lifecycle ─────────────────────────────────────────


def test_start_creates_running_row(db):
    rid = start_engine_run(db, engine="discovery", cycle=7)
    [row] = list_engine_runs(db)
    assert row.id == rid
    assert row.engine == "discovery"
    assert row.cycle == 7
    assert row.status == "running"
    assert row.finished_at is None
    assert row.api_calls == 0


def test_finish_closes_row_with_counters(db):
    rid = start_engine_run(db, engine="discovery", cycle=7)
    finish_engine_run(
        db, rid,
        status="success",
        api_calls=1,
        tokens_in=1234,
        tokens_out=567,
        chronicle_added=5,
        summary="three bullet points about recent activity",
    )
    [row] = list_engine_runs(db)
    assert row.status == "success"
    assert row.finished_at is not None
    assert row.api_calls == 1
    assert row.tokens_in == 1234
    assert row.tokens_out == 567
    assert row.chronicle_added == 5
    assert row.summary == "three bullet points about recent activity"


def test_finish_skipped_records_reason(db):
    rid = start_engine_run(db, engine="curiosity", cycle=2)
    finish_engine_run(
        db, rid, status="skipped",
        skip_reason="cold-start: no morning discovery substantive content",
    )
    [row] = list_engine_runs(db)
    assert row.status == "skipped"
    assert row.skip_reason and "cold-start" in row.skip_reason


def test_finish_failed_records_error(db):
    rid = start_engine_run(db, engine="reflection", cycle=10)
    finish_engine_run(
        db, rid, status="failed",
        skip_reason="provider rate-limited",
        api_calls=1,
    )
    [row] = list_engine_runs(db)
    assert row.status == "failed"
    assert row.api_calls == 1


def test_finish_summary_truncated_at_200_chars(db):
    rid = start_engine_run(db, engine="discovery", cycle=1)
    long_summary = "x" * 500
    finish_engine_run(db, rid, status="success", summary=long_summary)
    [row] = list_engine_runs(db)
    assert row.summary is not None
    assert len(row.summary) <= 200


# ── list_engine_runs filtering ────────────────────────────────────


def test_list_filters_by_engine(db):
    for engine in ("discovery", "curiosity", "reflection"):
        rid = start_engine_run(db, engine=engine, cycle=1)
        finish_engine_run(db, rid, status="success")
    assert len(list_engine_runs(db)) == 3
    assert len(list_engine_runs(db, engine="discovery")) == 1
    assert len(list_engine_runs(db, engine="curiosity")) == 1


def test_list_orders_newest_first(db):
    for cycle in (1, 2, 3):
        rid = start_engine_run(db, engine="discovery", cycle=cycle)
        finish_engine_run(db, rid, status="success")
    rows = list_engine_runs(db)
    assert [r.cycle for r in rows] == [3, 2, 1]


# ── engine_runs_summary aggregator ────────────────────────────────


def test_summary_counts_by_engine_and_status(db):
    # 2 discovery success, 1 discovery failed, 3 reflection success
    for _ in range(2):
        rid = start_engine_run(db, engine="discovery", cycle=1)
        finish_engine_run(db, rid, status="success")
    rid = start_engine_run(db, engine="discovery", cycle=2)
    finish_engine_run(db, rid, status="failed", skip_reason="boom")
    for _ in range(3):
        rid = start_engine_run(db, engine="reflection", cycle=1)
        finish_engine_run(db, rid, status="success")
    snap = engine_runs_summary(db)
    assert snap["discovery"]["success"] == 2
    assert snap["discovery"]["failed"] == 1
    assert snap["reflection"]["success"] == 3


def test_summary_empty(db):
    assert engine_runs_summary(db) == {}


# ── caller column on api_calls (P4) ──────────────────────────────


def test_record_api_call_persists_caller(db):
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-haiku-4-5-20251001",
        input_tokens=100, output_tokens=50,
        caller="discovery",
    )
    row = db.execute(
        "SELECT caller FROM api_calls WHERE cycle = 1"
    ).fetchone()
    assert row["caller"] == "discovery"


def test_record_api_call_caller_null_when_omitted(db):
    """Back-compat: pre-v4.69 callers don't pass `caller`."""
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-haiku-4-5-20251001",
        input_tokens=100, output_tokens=50,
    )
    row = db.execute("SELECT caller FROM api_calls WHERE cycle = 1").fetchone()
    assert row["caller"] is None


def test_caller_distinguishes_act_from_engine_spend(db):
    """Realistic split: 2 ACT calls + 1 reflection call. Aggregations
    by caller should match the inserted counts."""
    for _ in range(2):
        record_api_call(
            db, cycle=1, provider="openrouter",
            model_id="deepseek/deepseek-v4-pro",
            input_tokens=1000, output_tokens=500, caller="act",
        )
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-flash",
        input_tokens=2000, output_tokens=300, caller="reflection",
    )
    rows = db.execute(
        "SELECT caller, COUNT(*) AS n FROM api_calls "
        "WHERE caller IS NOT NULL GROUP BY caller"
    ).fetchall()
    by_caller = {r["caller"]: r["n"] for r in rows}
    assert by_caller == {"act": 2, "reflection": 1}
