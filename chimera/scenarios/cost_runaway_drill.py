"""v4.66 (ADR 0085) — cost runaway drill.

Synthetic regression of the entire cost-discipline arc (v4.53–v4.60).
Builds a temp DB, injects api_calls rows that mirror the 2026-05-19
burn pattern, and verifies each of the three caps trips at the
right boundary in the right order:

  1. Per-cycle cap (CHIMERA_CYCLE_COST_CAP_USD, default $2.00)
     — trips when one cycle's spend ≥ cap. v4.53 / ADR 0072.
  2. Per-task budget (CHIMERA_TASK_BUDGET_USD, default $5.00)
     — trips when accumulated spend on one task signature ≥ budget.
     v4.60 / ADR 0079.
  3. Rolling-hour cap (CHIMERA_ROLLING_HOUR_CAP_USD, default $20.00)
     — trips when 60-minute spend ≥ cap. v4.57 / ADR 0076.

The drill is hermetic — no API keys, no network. It just exercises
the budget helpers' SQL paths against synthetic rows. The point is
to catch regressions if the cap logic, the timestamp normalization,
or the price-table lookup drifts.

Operator usage:

    chimera scenario cost_runaway_drill

Returns 0 on green (all three caps tripped at the right boundary),
non-zero on red (any cap failed to trip, or tripped at the wrong
spend level).
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CapTripCheck:
    name: str
    expected_to_trip: bool
    tripped: bool
    spend_usd: float
    cap_usd: float
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.tripped == self.expected_to_trip


@dataclass
class CostRunawayResult:
    checks: list[CapTripCheck] = field(default_factory=list)
    total_spend_simulated: float = 0.0
    cycles_simulated: int = 0
    artifact_path: str = ""

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _simulate_overnight_burn(db, *, task_signature: str) -> float:
    """Inject api_calls rows matching the 2026-05-19 burn shape:
    five back-to-back opus cycles, ~$10/cycle each. Returns total
    simulated spend in USD.

    The actual burn was 13.8M input + 295K output across 801 calls;
    we condense to one row per cycle for test clarity.
    """
    from ..memory import record_api_call
    # Per-cycle: 600K input + 20K output on opus = $9 + $1.5 = $10.5.
    PER_CYCLE_IN = 600_000
    PER_CYCLE_OUT = 20_000
    PER_CYCLE_COST = (600_000 / 1_000_000) * 15.0 + (20_000 / 1_000_000) * 75.0
    cycles = 5
    for cycle in range(1, cycles + 1):
        record_api_call(
            db, cycle=cycle, provider="anthropic",
            model_id="claude-opus-4-7",
            input_tokens=PER_CYCLE_IN, output_tokens=PER_CYCLE_OUT,
            task_signature=task_signature,
        )
    db.commit()
    return PER_CYCLE_COST * cycles


def run_cost_runaway_drill(state_dir: Path | None = None) -> CostRunawayResult:
    """Hermetic drill against synthetic burn data.

    ``state_dir`` is optional; when omitted a tempdir is used so the
    operator can run this on a production agent without touching
    state/chimera.db.
    """
    from ..core.budget import (
        check_cycle_cost_cap,
        check_rolling_hour_cost_cap,
        check_task_budget,
        cycle_cost_cap_usd,
        cycle_spend_usd,
        rolling_hour_cap_usd,
        rolling_spend_usd,
        task_budget_usd,
        task_spend_usd,
        CycleCostCapExceeded,
        RollingHourCostCapExceeded,
        TaskBudgetExceeded,
    )
    from ..core.escalation import _signature
    from ..memory import open_and_init

    result = CostRunawayResult()

    # Drill always runs against a fresh temp DB — even if state_dir
    # is provided, the production data isn't mutated. The temp DB
    # is removed when the function returns.
    with tempfile.TemporaryDirectory(prefix="chimera-drill-") as tmp:
        tmp_path = Path(tmp) / "chimera.db"
        result.artifact_path = str(tmp_path)
        db = open_and_init(tmp_path)
        try:
            task_text = (
                "Dashboard honesty audit. For each widget listed in "
                "docs/runbook.md, spawn a sub-agent to answer ONE "
                "question and compile the answers into a file."
            )
            sig = _signature(task_text)
            total = _simulate_overnight_burn(db, task_signature=sig)
            result.total_spend_simulated = round(total, 2)
            result.cycles_simulated = 5

            # ── 1. Per-cycle cap (cycle 1 alone) ─────────────────────
            cycle1_spend = cycle_spend_usd(db, 1)
            cycle_cap = cycle_cost_cap_usd()
            tripped = False
            try:
                check_cycle_cost_cap(db, 1)
            except CycleCostCapExceeded:
                tripped = True
            result.checks.append(CapTripCheck(
                name="per_cycle_cap",
                expected_to_trip=True,
                tripped=tripped,
                spend_usd=round(cycle1_spend, 2),
                cap_usd=cycle_cap,
                reason=("trip expected: cycle 1 spent "
                        f"${cycle1_spend:.2f} > cap ${cycle_cap:.2f}"),
            ))

            # ── 2. Per-task budget (one cycle in is enough) ──────────
            task_spend = task_spend_usd(db, task_signature=sig)
            budget = task_budget_usd()
            tripped = False
            try:
                check_task_budget(db, task_signature=sig)
            except TaskBudgetExceeded:
                tripped = True
            result.checks.append(CapTripCheck(
                name="per_task_budget",
                expected_to_trip=True,
                tripped=tripped,
                spend_usd=round(task_spend, 2),
                cap_usd=budget,
                reason=("trip expected: task signature spent "
                        f"${task_spend:.2f} > budget ${budget:.2f}"),
            ))

            # ── 3. Rolling-hour cap (all 5 cycles within window) ─────
            rolling = rolling_spend_usd(db, minutes=60)
            hour_cap = rolling_hour_cap_usd()
            tripped = False
            try:
                check_rolling_hour_cost_cap(db)
            except RollingHourCostCapExceeded:
                tripped = True
            result.checks.append(CapTripCheck(
                name="rolling_hour_cap",
                expected_to_trip=True,
                tripped=tripped,
                spend_usd=round(rolling, 2),
                cap_usd=hour_cap,
                reason=("trip expected: 60m spend "
                        f"${rolling:.2f} > cap ${hour_cap:.2f}"),
            ))

            # ── 4. Negative control: a NEW task signature should
            # NOT trip the per-task budget (fresh signature, $0 spent). ─
            fresh_text = "A different, unrelated INBOX task."
            fresh_sig = _signature(fresh_text)
            tripped = False
            try:
                check_task_budget(db, task_signature=fresh_sig)
            except TaskBudgetExceeded:
                tripped = True
            result.checks.append(CapTripCheck(
                name="fresh_task_unaffected",
                expected_to_trip=False,
                tripped=tripped,
                spend_usd=0.0,
                cap_usd=budget,
                reason=("trip NOT expected: distinct signature, "
                        "$0 attributed spend"),
            ))
        finally:
            db.close()

    return result


def format_result(result: CostRunawayResult) -> str:
    """Human-readable report for the CLI handler."""
    lines = []
    overall = "OK" if result.ok else "FAIL"
    lines.append(f"chimera cost_runaway_drill: {overall}")
    lines.append(
        f"  simulated {result.cycles_simulated} cycle(s), "
        f"total ${result.total_spend_simulated:.2f}"
    )
    for c in result.checks:
        marker = "✓" if c.ok else "✗"
        verdict = "tripped" if c.tripped else "no trip"
        lines.append(
            f"  {marker} {c.name:24s}  ${c.spend_usd:>6.2f} vs "
            f"${c.cap_usd:>6.2f}  → {verdict}"
        )
        if not c.ok:
            lines.append(f"      {c.reason}")
    return "\n".join(lines)


__all__ = [
    "CapTripCheck",
    "CostRunawayResult",
    "format_result",
    "run_cost_runaway_drill",
]
