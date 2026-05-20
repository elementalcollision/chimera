"""v4.66 (ADR 0085) — cost runaway drill regression test.

Runs the hermetic drill and asserts all four checks pass. This is
the regression net for the v4.53–v4.60 cost-discipline arc: if any
of the budget helpers, the SQL paths, the price table, or the
timestamp normalization drifts, this test fails.
"""

from __future__ import annotations

from chimera.scenarios import run_cost_runaway_drill


def test_drill_passes_against_synthetic_burn():
    """Replay the 2026-05-19 overnight burn pattern (5 cycles × $10.5
    on opus) against the in-process budget helpers. All three caps
    must trip; a fresh signature must NOT trip the per-task budget."""
    result = run_cost_runaway_drill()
    assert result.ok, "drill checks: " + "; ".join(
        f"{c.name}: {c.reason}" for c in result.checks if not c.ok
    )
    # Sanity asserts on the simulated burn shape.
    assert result.cycles_simulated == 5
    # 5 × $10.50 = $52.50.
    assert result.total_spend_simulated == 52.50


def test_drill_per_cycle_check_tripped():
    result = run_cost_runaway_drill()
    cycle_check = next(c for c in result.checks if c.name == "per_cycle_cap")
    assert cycle_check.tripped
    # Cycle 1 alone spent $10.50, well over the $2 default cap.
    assert cycle_check.spend_usd > cycle_check.cap_usd


def test_drill_task_budget_check_tripped():
    result = run_cost_runaway_drill()
    task_check = next(c for c in result.checks if c.name == "per_task_budget")
    assert task_check.tripped
    # 5 cycles attributed to one signature → $52.50, over $5 budget.
    assert task_check.spend_usd > task_check.cap_usd


def test_drill_rolling_hour_check_tripped():
    result = run_cost_runaway_drill()
    rolling_check = next(c for c in result.checks if c.name == "rolling_hour_cap")
    assert rolling_check.tripped
    # All 5 cycles within the synthetic 60-min window.
    assert rolling_check.spend_usd > rolling_check.cap_usd


def test_drill_fresh_signature_untouched():
    """Negative control: a fresh task signature has $0 attributed
    spend and must NOT trip the per-task budget."""
    result = run_cost_runaway_drill()
    fresh_check = next(c for c in result.checks if c.name == "fresh_task_unaffected")
    assert fresh_check.expected_to_trip is False
    assert fresh_check.tripped is False
    assert fresh_check.spend_usd == 0.0
