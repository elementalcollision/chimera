"""v4.60 (ADR 0079) — per-task budget cap.

The cycle cap stops one runaway cycle; the rolling-hour cap stops
slow burns; the per-task budget stops a stuck task that keeps being
re-promoted by escalation memory across multiple cycles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.budget import (
    TaskBudgetExceeded,
    check_task_budget,
    task_budget_usd,
    task_spend_usd,
)
from chimera.core.escalation import _signature
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── env reader ─────────────────────────────────────────────────────


def test_budget_default_is_five_dollars(monkeypatch):
    monkeypatch.delenv("CHIMERA_TASK_BUDGET_USD", raising=False)
    assert task_budget_usd() == pytest.approx(5.00)


def test_budget_env_override(monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "12.50")
    assert task_budget_usd() == pytest.approx(12.50)


def test_budget_zero_disables(monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "0")
    assert task_budget_usd() == 0.0


def test_budget_malformed_falls_back(monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "not-a-number")
    assert task_budget_usd() == pytest.approx(5.00)


# ── task_spend_usd accumulation ────────────────────────────────────


def test_spend_empty(db):
    assert task_spend_usd(db, task_signature="any") == 0.0


def test_spend_attribution_by_signature(db):
    """Two different tasks should never bleed spend into each other."""
    sig_a = _signature("Refactor the authentication module")
    sig_b = _signature("Inventory dashboard widgets and document SQL")
    assert sig_a != sig_b, "test fixture: signatures must differ"
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,  # $15
        task_signature=sig_a,
    )
    record_api_call(
        db, cycle=2, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=0,  # ≈ $0.44
        task_signature=sig_b,
    )
    db.commit()
    assert task_spend_usd(db, task_signature=sig_a) == pytest.approx(15.00, abs=0.01)
    assert task_spend_usd(db, task_signature=sig_b) == pytest.approx(0.435, abs=0.01)


def test_spend_sums_across_cycles(db):
    """Multi-cycle re-attempts on the same signature should sum."""
    sig = _signature("Dashboard honesty audit — sub-agent fanout")
    for cycle in (1, 2, 3):
        record_api_call(
            db, cycle=cycle, provider="anthropic", model_id="claude-opus-4-7",
            input_tokens=500_000, output_tokens=0,  # $7.50 each
            task_signature=sig,
        )
    db.commit()
    # 3 × $7.50 = $22.50.
    assert task_spend_usd(db, task_signature=sig) == pytest.approx(22.50, abs=0.01)


def test_spend_ignores_errored_calls(db):
    sig = _signature("rate-limited task")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
        error="rate_limited",
        task_signature=sig,
    )
    db.commit()
    assert task_spend_usd(db, task_signature=sig) == 0.0


def test_spend_empty_signature_returns_zero(db):
    """Defensive: empty signature shouldn't accidentally match NULL rows."""
    assert task_spend_usd(db, task_signature="") == 0.0


# ── check_task_budget ─────────────────────────────────────────────


def test_check_no_op_under_budget(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "5.00")
    sig = _signature("cheap task")
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=0,  # ~$0.44
        task_signature=sig,
    )
    db.commit()
    check_task_budget(db, task_signature=sig)  # must not raise


def test_check_raises_over_budget(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "5.00")
    sig = _signature("expensive recurring task")
    # 3 cycles × $7.50 each on opus = $22.50, well over $5.
    for cycle in (1, 2, 3):
        record_api_call(
            db, cycle=cycle, provider="anthropic", model_id="claude-opus-4-7",
            input_tokens=500_000, output_tokens=0,
            task_signature=sig,
        )
    db.commit()
    with pytest.raises(TaskBudgetExceeded) as ei:
        check_task_budget(db, task_signature=sig)
    assert ei.value.budget_usd == pytest.approx(5.00)
    assert ei.value.spend_usd == pytest.approx(22.50, abs=0.01)
    assert ei.value.signature == sig


def test_check_disabled_when_budget_zero(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "0")
    sig = _signature("anything")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=10_000_000, output_tokens=1_000_000,
        task_signature=sig,
    )
    db.commit()
    check_task_budget(db, task_signature=sig)  # must not raise


def test_check_no_op_for_empty_signature(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "5.00")
    check_task_budget(db, task_signature="")  # must not raise


# ── overnight-burn replay ─────────────────────────────────────────


def test_overnight_burn_would_trip_after_first_bad_cycle(db, monkeypatch):
    """The dashboard-audit task burnt ~$10/cycle. With the default
    $5 budget, the SECOND cycle's check would have tripped — before
    even calling the provider for round 1 of cycle 2."""
    monkeypatch.setenv("CHIMERA_TASK_BUDGET_USD", "5.00")
    sig = _signature("Dashboard honesty audit — spawn 14 sub-agents")
    # First cycle's $10 spend on opus.
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=600_000, output_tokens=20_000,  # ~$10.5
        task_signature=sig,
    )
    db.commit()
    # Now at the start of cycle 2, the budget check should trip.
    with pytest.raises(TaskBudgetExceeded) as ei:
        check_task_budget(db, task_signature=sig)
    assert ei.value.spend_usd > 5.0
