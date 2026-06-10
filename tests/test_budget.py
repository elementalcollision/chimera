"""Direct unit tests for :mod:`chimera.core.budget`.

The three cost caps (per-cycle v4.53, rolling-hour v4.57, per-task
v4.60) each have a scenario-level test module already
(test_cycle_cost_cap / test_rolling_hour_cap / test_task_budget), and
the adaptive round budget + Honcho helpers are pinned in
test_adaptive_budget / test_honcho_inspired / test_reasoning_tier_wired.
This module covers the surface those files miss: boundary conditions
(exactly-at-cap, negative/whitespace env values), input clamps, the
rolling-window minute clamp and timestamp normalization, the
pre-v4.60-schema fallback, exception message formatting, and the
remaining pure helpers.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import chimera.core.budget as budget
from chimera.core.budget import (
    Context,
    CycleCostCapExceeded,
    RollingHourCostCapExceeded,
    TaskBudgetExceeded,
    _message_tokens,
    _price_table,
    check_cycle_cost_cap,
    check_rolling_hour_cost_cap,
    check_task_budget,
    cycle_cost_cap_usd,
    cycle_spend_usd,
    dynamic_max_rounds,
    rolling_hour_cap_usd,
    rolling_spend_usd,
    task_budget_usd,
    task_spend_usd,
)
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# claude-opus-4-7 prices: $15/Mtok input, $75/Mtok output (see
# test_cycle_cost_cap.py). 1M input tokens = exactly $15.00.
_OPUS = "claude-opus-4-7"


def _record_opus(db, *, cycle: int = 1, input_tokens: int = 1_000_000, **kw) -> None:
    record_api_call(
        db, cycle=cycle, provider="anthropic", model_id=_OPUS,
        input_tokens=input_tokens, output_tokens=0, **kw,
    )


# ── env readers: negative + whitespace values ──────────────────────

_ENV_READERS = [
    (cycle_cost_cap_usd, "CHIMERA_CYCLE_COST_CAP_USD", 2.00),
    (rolling_hour_cap_usd, "CHIMERA_ROLLING_HOUR_CAP_USD", 20.00),
    (task_budget_usd, "CHIMERA_TASK_BUDGET_USD", 5.00),
]


@pytest.mark.parametrize(("reader", "var", "_default"), _ENV_READERS)
def test_negative_env_value_clamps_to_zero(monkeypatch, reader, var, _default):
    """Negative caps make no sense; they clamp to 0 (= disabled)."""
    monkeypatch.setenv(var, "-3.50")
    assert reader() == 0.0


@pytest.mark.parametrize(("reader", "var", "default"), _ENV_READERS)
def test_whitespace_env_value_falls_back_to_default(monkeypatch, reader, var, default):
    monkeypatch.setenv(var, "   ")
    assert reader() == pytest.approx(default)


@pytest.mark.parametrize(("reader", "var", "default"), _ENV_READERS)
def test_partially_numeric_env_value_falls_back_to_default(
    monkeypatch, reader, var, default
):
    monkeypatch.setenv(var, "2.5usd")
    assert reader() == pytest.approx(default)


# ── exactly-at-cap boundaries (>= trips, not just >) ───────────────


def test_check_cycle_cap_trips_exactly_at_cap(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "15.00")
    _record_opus(db, cycle=1)  # exactly $15.00
    with pytest.raises(CycleCostCapExceeded) as ei:
        check_cycle_cost_cap(db, cycle=1)
    assert ei.value.spend_usd == pytest.approx(15.00)
    assert ei.value.cap_usd == pytest.approx(15.00)


def test_check_rolling_cap_trips_exactly_at_cap(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "15.00")
    _record_opus(db)  # fresh timestamp, inside the window, exactly $15.00
    with pytest.raises(RollingHourCostCapExceeded):
        check_rolling_hour_cost_cap(db)


def test_check_task_budget_trips_exactly_at_budget(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "15.00")
    _record_opus(db, task_signature="sig-exact")
    with pytest.raises(TaskBudgetExceeded):
        check_task_budget(db, task_signature="sig-exact")


def test_check_cycle_cap_disabled_by_negative_env(db, monkeypatch):
    """Negative env clamps to 0, and a 0 cap means no enforcement."""
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "-1")
    _record_opus(db, cycle=1, input_tokens=10_000_000)  # $150
    check_cycle_cost_cap(db, cycle=1)  # must not raise


# ── dynamic_max_rounds input clamps ────────────────────────────────


def test_dynamic_max_rounds_base_below_one_clamps_to_one():
    assert dynamic_max_rounds("Just say hello.", base=0) == 1
    assert dynamic_max_rounds("Just say hello.", base=-7) == 1


def test_dynamic_max_rounds_cap_below_base_is_raised_to_base():
    # Shape budget = 12 + 4 artifacts... here 2 artifacts × 4 = 20,
    # but cap=4 < base=12 is bumped to 12, so the result floors at base.
    text = "Write to `state/a.log` and to `mind/b.md`."
    assert dynamic_max_rounds(text, base=12, per_artifact=4, cap=4) == 12


def test_dynamic_max_rounds_tier_multiplier_rounds_to_int():
    # base=5 × sonnet 1.5 = 7.5 → banker's rounding via round() → 8.
    result = dynamic_max_rounds("Just say hello.", base=5, tier="sonnet")
    assert isinstance(result, int)
    assert result == 8


# ── rolling window: minute clamp + timestamp normalization ─────────


def test_rolling_spend_minutes_clamped_to_minimum_one(db):
    """minutes=0 clamps to a 1-minute window, not an empty/invalid SQL."""
    _record_opus(db, cycle=1)
    db.execute(
        "UPDATE api_calls SET created_at = datetime('now', '-30 minutes') "
        "WHERE cycle = 1"
    )
    db.commit()
    assert rolling_spend_usd(db, minutes=0) == 0.0
    assert rolling_spend_usd(db, minutes=60) == pytest.approx(15.00, abs=0.01)


def test_rolling_spend_minutes_clamped_to_one_day(db):
    """An enormous minutes value clamps to 1440 (24h)."""
    _record_opus(db, cycle=1)  # will be backdated 2 days — outside even 24h
    _record_opus(db, cycle=2)  # will be backdated 12 hours — inside 24h
    db.execute(
        "UPDATE api_calls SET created_at = datetime('now', '-2 days') WHERE cycle = 1"
    )
    db.execute(
        "UPDATE api_calls SET created_at = datetime('now', '-12 hours') WHERE cycle = 2"
    )
    db.commit()
    assert rolling_spend_usd(db, minutes=10_000_000) == pytest.approx(15.00, abs=0.01)


def test_rolling_spend_normalizes_iso_t_timestamps(db):
    """Production stamps ISO 'T'-separated, tz-suffixed timestamps; raw
    string comparison against SQLite's space-separated datetime('now')
    would falsely count an old row as recent. The datetime() wrap in
    rolling_spend_usd must normalize and exclude it."""
    _record_opus(db, cycle=1)
    two_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).replace(microsecond=0).isoformat()  # e.g. 2026-06-10T09:24:00+00:00
    db.execute(
        "UPDATE api_calls SET created_at = ? WHERE cycle = 1", (two_hours_ago,)
    )
    db.commit()
    assert rolling_spend_usd(db, minutes=60) == 0.0


# ── pricing: unknown models + price-table cache ────────────────────


def test_cycle_spend_unknown_model_priced_at_zero(db):
    record_api_call(
        db, cycle=1, provider="openrouter", model_id="totally/unknown-model",
        input_tokens=50_000_000, output_tokens=5_000_000,
    )
    assert cycle_spend_usd(db, cycle=1) == 0.0


def test_price_table_is_built_once_and_cached():
    first = _price_table()
    second = _price_table()
    assert first is second
    assert budget._PRICE_TABLE is first
    assert _OPUS in first


# ── task spend: pre-v4.60 schema fallback ──────────────────────────


def test_task_spend_returns_zero_on_pre_v460_schema():
    """A DB whose api_calls table predates the task_signature column
    must not crash the budget check — it degrades to $0 spend."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE api_calls ("
        "  cycle INTEGER, provider TEXT, model_id TEXT,"
        "  input_tokens INTEGER, output_tokens INTEGER, error TEXT)"
    )
    conn.execute(
        "INSERT INTO api_calls VALUES (1, 'anthropic', ?, 1000000, 0, NULL)",
        (_OPUS,),
    )
    assert task_spend_usd(conn, task_signature="any-sig") == 0.0
    conn.close()


def test_check_task_budget_no_op_on_pre_v460_schema(monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "0.01")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE api_calls ("
        "  cycle INTEGER, provider TEXT, model_id TEXT,"
        "  input_tokens INTEGER, output_tokens INTEGER, error TEXT)"
    )
    check_task_budget(conn, task_signature="any-sig")  # must not raise
    conn.close()


# ── exception message formatting ───────────────────────────────────


def test_cycle_cap_exceeded_message_carries_values():
    exc = CycleCostCapExceeded(spend_usd=3.456, cap_usd=2.0, cycle=42)
    assert exc.spend_usd == 3.456
    assert exc.cap_usd == 2.0
    assert exc.cycle == 42
    assert str(exc) == "cycle 42 spend $3.46 exceeds cap $2.00"


def test_rolling_cap_exceeded_defaults_to_sixty_minute_window():
    exc = RollingHourCostCapExceeded(spend_usd=25.0, cap_usd=20.0)
    assert exc.window_minutes == 60
    assert str(exc) == "rolling-60m spend $25.00 exceeds cap $20.00"


def test_task_budget_exceeded_truncates_long_signature_in_message():
    sig = "x" * 100
    exc = TaskBudgetExceeded(spend_usd=6.0, budget_usd=5.0, signature=sig)
    assert exc.signature == sig  # attribute keeps the full signature
    assert "x" * 60 + "…" in str(exc)
    assert "x" * 61 not in str(exc)


def test_task_budget_exceeded_short_signature_not_truncated():
    exc = TaskBudgetExceeded(spend_usd=6.0, budget_usd=5.0, signature="short-sig")
    assert "short-sig)" in str(exc)
    assert "…" not in str(exc)


# ── _message_tokens (pure helper) ──────────────────────────────────


def test_message_tokens_handles_multimodal_list_content():
    """List-shaped content (openai multimodal parts) is flattened: dict
    parts contribute their 'text', non-dict parts their str()."""
    msg = {
        "role": "user",
        "content": [{"type": "text", "text": "hello"}, "raw-part"],
    }
    expected = budget._estimate_tokens("hello raw-part") + 4
    assert _message_tokens(msg) == expected


def test_message_tokens_missing_content_counts_framing_only():
    # No content → 0 content tokens + 4 framing tokens.
    assert _message_tokens({"role": "assistant"}) == 4


# ── Context.to_openai trim floor ───────────────────────────────────


def test_context_to_openai_never_trims_below_three_messages():
    """Even when wildly over budget, head + last two messages survive."""
    messages = [
        {"role": "user", "content": "HEAD " + "a" * 8_000},
        {"role": "assistant", "content": "PENULT " + "b" * 8_000},
        {"role": "user", "content": "LAST " + "c" * 8_000},
    ]
    ctx = Context(system="sys", messages=messages, max_tokens=10)
    payload = ctx.to_openai()
    contents = [m["content"] for m in payload["messages"]]
    assert contents[0] == "sys"
    assert len(payload["messages"]) == 4  # system + all 3 preserved
    assert contents[1].startswith("HEAD ")
    assert contents[2].startswith("PENULT ")
    assert contents[3].startswith("LAST ")


def test_context_to_openai_does_not_mutate_messages():
    """Trimming works on a copy; the Context's message list is untouched."""
    messages = [
        {"role": "user", "content": "HEAD " + "a" * 4_000},
        {"role": "assistant", "content": "MID " + "b" * 4_000},
        {"role": "user", "content": "MID2 " + "c" * 4_000},
        {"role": "assistant", "content": "PENULT"},
        {"role": "user", "content": "LAST"},
    ]
    ctx = Context(system="sys", messages=messages, max_tokens=200)
    payload = ctx.to_openai()
    assert len(payload["messages"]) < 1 + len(messages)  # something dropped
    assert len(ctx.messages) == 5  # original list intact
