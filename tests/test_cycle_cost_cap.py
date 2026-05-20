"""v4.53 — per-cycle USD cost cap (ADR 0072).

After the 2026-05-19 overnight burn ($229 of opus across one stuck
task), ACT now checks accumulated cycle spend at the top of each round
and raises :class:`CycleCostCapExceeded` if it crosses the cap. This
test pins the spend computation, the env-var override, and the
"cost_cap does NOT promote tier" contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.budget import (
    CycleCostCapExceeded,
    check_cycle_cost_cap,
    cycle_cost_cap_usd,
    cycle_spend_usd,
)
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_cap_default_is_two_dollars(monkeypatch):
    monkeypatch.delenv("CHIMERA_CYCLE_COST_CAP_USD", raising=False)
    assert cycle_cost_cap_usd() == pytest.approx(2.00)


def test_cap_reads_env_override(monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "5.50")
    assert cycle_cost_cap_usd() == pytest.approx(5.50)


def test_cap_zero_disables(monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "0")
    assert cycle_cost_cap_usd() == 0.0


def test_cap_malformed_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "not-a-number")
    assert cycle_cost_cap_usd() == pytest.approx(2.00)


def test_cycle_spend_zero_when_empty(db):
    assert cycle_spend_usd(db, cycle=1) == 0.0


def test_cycle_spend_matches_opus_pricing(db):
    # claude-opus-4-7: $15/Mtok input, $75/Mtok output
    # 1M input + 0.1M output = $15 + $7.5 = $22.50
    record_api_call(
        db, cycle=7, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=100_000,
    )
    assert cycle_spend_usd(db, cycle=7) == pytest.approx(22.50, abs=0.01)


def test_cycle_spend_matches_deepseek_pricing(db):
    # deepseek-v4-pro: $0.435/Mtok input, $0.87/Mtok output
    # Same 1M+0.1M token shape should be ~~34× cheaper than opus
    record_api_call(
        db, cycle=8, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=100_000,
    )
    spend = cycle_spend_usd(db, cycle=8)
    assert spend == pytest.approx(0.435 + 0.087, abs=0.001)


def test_cycle_spend_ignores_errored_calls(db):
    record_api_call(
        db, cycle=9, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=100_000,
        error="rate_limited",
    )
    # Errored calls don't bill us, so they don't count toward the cap.
    assert cycle_spend_usd(db, cycle=9) == 0.0


def test_cycle_spend_scoped_by_cycle(db):
    record_api_call(
        db, cycle=10, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
    )
    record_api_call(
        db, cycle=11, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=2_000_000, output_tokens=0,
    )
    assert cycle_spend_usd(db, cycle=10) == pytest.approx(15.00)
    assert cycle_spend_usd(db, cycle=11) == pytest.approx(30.00)


def test_check_cap_no_op_when_under(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "2.00")
    # ~$0.522 spend on deepseek-pro
    record_api_call(
        db, cycle=12, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=100_000,
    )
    check_cycle_cost_cap(db, cycle=12)  # must not raise


def test_check_cap_raises_when_over(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "2.00")
    # 200K input + 0 output on opus = $3, over cap
    record_api_call(
        db, cycle=13, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=200_000, output_tokens=0,
    )
    with pytest.raises(CycleCostCapExceeded) as ei:
        check_cycle_cost_cap(db, cycle=13)
    assert ei.value.cycle == 13
    assert ei.value.cap_usd == pytest.approx(2.00)
    assert ei.value.spend_usd == pytest.approx(3.00)


def test_check_cap_disabled_when_zero(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "0")
    # Massive spend, but cap=0 means no enforcement
    record_api_call(
        db, cycle=14, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=10_000_000, output_tokens=1_000_000,
    )
    check_cycle_cost_cap(db, cycle=14)  # must not raise


def test_overnight_burn_would_have_tripped_at_cycle_one(db, monkeypatch):
    """The 2026-05-19 overnight averaged ~$10 per stuck cycle.
    With cap=2.00, the very first cycle's spend would have raised."""
    monkeypatch.setenv("CHIMERA_CYCLE_COST_CAP_USD", "2.00")
    # First cycle of the overnight burn: ~17K input tokens × 30 rounds
    # on opus = 510K input tokens, plus ~10K output × 30 = 300K output.
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=510_000, output_tokens=300_000,
    )
    # 0.51 × $15 + 0.3 × $75 = $7.65 + $22.50 = $30.15 — way over $2.
    with pytest.raises(CycleCostCapExceeded) as ei:
        check_cycle_cost_cap(db, cycle=1)
    assert ei.value.spend_usd > 20.0
