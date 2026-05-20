"""v4.57 (ADR 0076) — rolling-hour spend cap.

Per-cycle cap (v4.53) catches one runaway cycle; rolling-hour cap
catches the slow burn across multiple cycles. Together they're the
short-window + long-window cost discipline pair.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from chimera.core.budget import (
    RollingHourCostCapExceeded,
    check_rolling_hour_cost_cap,
    rolling_hour_cap_usd,
    rolling_spend_usd,
)
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── env reader ─────────────────────────────────────────────────────


def test_rolling_cap_default_is_twenty_dollars(monkeypatch):
    monkeypatch.delenv("CHIMERA_ROLLING_HOUR_CAP_USD", raising=False)
    assert rolling_hour_cap_usd() == pytest.approx(20.00)


def test_rolling_cap_reads_env_override(monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "50.00")
    assert rolling_hour_cap_usd() == pytest.approx(50.00)


def test_rolling_cap_zero_disables(monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "0")
    assert rolling_hour_cap_usd() == 0.0


def test_rolling_cap_malformed_falls_back(monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "not-a-number")
    assert rolling_hour_cap_usd() == pytest.approx(20.00)


# ── spend window ──────────────────────────────────────────────────


def test_rolling_spend_zero_when_empty(db):
    assert rolling_spend_usd(db, minutes=60) == 0.0


def test_rolling_spend_counts_recent_only(db):
    """Calls within the window count; calls outside don't.

    SQLite's datetime('now', '-N minutes') is anchored to NOW; the
    only reliable way to test "outside the window" is to write an
    explicit older created_at. record_api_call always stamps with
    _utc_now_iso, so we backdate via direct UPDATE.
    """
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,  # $15
    )
    record_api_call(
        db, cycle=2, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,  # $15
    )
    # Backdate the first row 2 hours so it's outside the 60m window.
    # Use SQLite's own datetime format (space separator) to match the
    # format the query compares against — ISO 'T' separator string-orders
    # higher than space and would falsely look "newer".
    db.execute(
        "UPDATE api_calls SET created_at = datetime('now', '-2 hours') WHERE cycle = 1"
    )
    db.commit()
    # Only the recent ~$15 should count.
    spend = rolling_spend_usd(db, minutes=60)
    assert spend == pytest.approx(15.00, abs=0.01)


def test_rolling_spend_ignores_errored_calls(db):
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
        error="rate_limited",
    )
    assert rolling_spend_usd(db, minutes=60) == 0.0


# ── check_rolling_hour_cost_cap ───────────────────────────────────


def test_check_rolling_no_op_under_cap(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "20.00")
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=100_000,  # ≈ $0.52
    )
    check_rolling_hour_cost_cap(db)  # must not raise


def test_check_rolling_raises_over_cap(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "20.00")
    # Two opus cycles within the hour @ $15 each = $30.
    for cycle in (1, 2):
        record_api_call(
            db, cycle=cycle, provider="anthropic",
            model_id="claude-opus-4-7",
            input_tokens=1_000_000, output_tokens=0,
        )
    with pytest.raises(RollingHourCostCapExceeded) as ei:
        check_rolling_hour_cost_cap(db)
    assert ei.value.cap_usd == pytest.approx(20.00)
    assert ei.value.spend_usd == pytest.approx(30.00)
    assert ei.value.window_minutes == 60


def test_check_rolling_disabled_when_zero(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "0")
    # Enormous spend, cap=0 means no enforcement.
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=10_000_000, output_tokens=1_000_000,
    )
    check_rolling_hour_cost_cap(db)  # must not raise


def test_overnight_burn_rolling_hour(db, monkeypatch):
    """The 2026-05-19 burn was 13.8M input + 295K output on opus over
    135 minutes. Even with the per-cycle cap at $2, the rolling-hour
    cap at $20 would have tripped well inside the first hour."""
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "20.00")
    # First-hour ≈ 6M input tokens (135min × 60/135 ≈ 60min worth of 13.8M).
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=6_000_000, output_tokens=130_000,
    )
    # 6 × $15 + 0.13 × $75 = $90 + $9.75 = $99.75 — well over $20.
    with pytest.raises(RollingHourCostCapExceeded) as ei:
        check_rolling_hour_cost_cap(db)
    assert ei.value.spend_usd > 50.0


# ── cost_usd column population (companion fix) ────────────────────


def test_record_api_call_persists_cost_usd_when_supplied(db):
    """v4.57: ACT now passes cost_usd explicitly. Verify the column
    accepts the value end-to-end."""
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
        cost_usd=15.00,
    )
    row = db.execute(
        "SELECT cost_usd FROM api_calls WHERE cycle = 1"
    ).fetchone()
    assert row["cost_usd"] == pytest.approx(15.00)
