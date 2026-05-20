"""v4.59 (ADR 0078) — pre-flight cost estimation for an INBOX.

Predicts the expected USD spend of running every open `- [ ]` task in
``mind/INBOX.md`` once. Anchored to historical data:

  * Predicted starting tier per task via
    :func:`chimera.core.escalation.recommended_tier` (which already
    considers the research-task floor and prior escalation memory).
  * Median per-cycle spend per model from ``api_calls`` history; if
    no history, fall back to a tier-typical token estimate × current
    price table.
  * Cycles-needed per task: 1 baseline + N for prior failures (each
    failure pushed the tier up one rung; assume the next attempt
    needs another cycle).

The result is a heuristic. Real spend depends on round budget, tool
fan-out, and whether any task trips the per-cycle cap. The estimate
is intentionally pessimistic in absence of history (we'd rather
warn high and have the operator decide than warn low and burn cash).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from .budget import _price_table
from .escalation import (
    _signature,
    recommended_tier,
)
from .mind import parse_inbox

# Typical token shape per cycle at each tier, when no historical data
# is available. Tuned to a conservative "average research-shaped
# cycle" rather than min/max — the agent burns more on hard cycles,
# so the estimate skews higher than recent observation. Reviewable in
# tests/test_cost_estimate.py.
_TIER_FALLBACK_TOKENS: dict[str, tuple[int, int]] = {
    "haiku": (8_000, 1_500),    # ~10K total typical haiku cycle
    "sonnet": (15_000, 3_000),  # heavier reasoning, more rounds
    "opus": (25_000, 5_000),    # the v4.53 ladder maps this to deepseek-v4-pro,
                                # but token shape stays opus-cycle-like
}


@dataclass
class TaskCostEstimate:
    """Per-task projection. ``model_id`` is the rung that tier resolves to."""

    task_text: str
    tier: str
    model_id: str
    estimated_cycles: int
    estimated_usd: float
    # Diagnostic provenance:
    used_history: bool = False
    n_historical_cycles: int = 0
    prior_failures: int = 0


@dataclass
class InboxCostEstimate:
    """Roll-up across every open task."""

    tasks: list[TaskCostEstimate] = field(default_factory=list)
    total_usd: float = 0.0
    total_cycles: int = 0
    n_tasks: int = 0


def _per_cycle_costs_by_model(db: sqlite3.Connection) -> dict[str, list[float]]:
    """Build ``model_id -> [per_cycle_usd, …]`` from api_calls history.

    One element per (model_id, cycle) tuple. Errored rows excluded.
    """
    try:
        rows = db.execute(
            "SELECT model_id, cycle, "
            "  COALESCE(SUM(input_tokens), 0) AS in_tok, "
            "  COALESCE(SUM(output_tokens), 0) AS out_tok "
            "FROM api_calls WHERE error IS NULL "
            "GROUP BY model_id, cycle"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    table = _price_table()
    out: dict[str, list[float]] = {}
    for r in rows:
        model_id = r["model_id"]
        in_price, out_price = table.get(model_id, (0.0, 0.0))
        cost = (
            (int(r["in_tok"]) / 1_000_000.0) * in_price
            + (int(r["out_tok"]) / 1_000_000.0) * out_price
        )
        if cost <= 0:
            continue
        out.setdefault(model_id, []).append(cost)
    return out


def _resolve_tier_to_model(tier: str) -> str:
    """Return the cheapest-qualifying ``model_id`` for ``tier``.

    Used to look up historical cycle costs against the actual model
    the agent would call (after the v4.53 ladder inversion, ``opus``
    tier defaults to deepseek-v4-pro, not claude-opus-4-7).
    """
    from chimera.providers.tiers import select_rung
    try:
        rung = select_rung(tier, requires_tools=True)
    except (ValueError, RuntimeError):
        return ""
    return rung.config.model_id


def _count_prior_failures(db: sqlite3.Connection, task_text: str) -> int:
    """Number of task_escalations rows with overlapping signature.

    Same Jaccard-overlap shape as ``recommended_tier`` but returns a
    count rather than the promoted tier. Used to estimate
    cycles-needed (each prior failure suggests one more cycle).
    """
    incoming = _signature(task_text)
    if not incoming:
        return 0
    incoming_set = set(incoming.split(","))
    try:
        rows = db.execute(
            "SELECT signature FROM task_escalations"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for r in rows:
        existing = set((r["signature"] or "").split(","))
        if not existing or not incoming_set:
            continue
        union = incoming_set | existing
        if not union:
            continue
        overlap = len(incoming_set & existing) / len(union)
        if overlap >= 0.5:
            n += 1
    return n


def estimate_task_cost(
    db: sqlite3.Connection,
    task_text: str,
    *,
    history: dict[str, list[float]] | None = None,
    default_tier: str = "haiku",
) -> TaskCostEstimate:
    """Project the USD cost of running ``task_text`` once.

    The caller may supply a pre-built ``history`` dict (from
    :func:`_per_cycle_costs_by_model`) to amortise the SELECT across
    many tasks. If omitted we build it from ``db`` each call.
    """
    if history is None:
        history = _per_cycle_costs_by_model(db)

    tier = recommended_tier(db, task_text=task_text, default_tier=default_tier)
    model_id = _resolve_tier_to_model(tier)
    prior = _count_prior_failures(db, task_text)
    cycles = max(1, 1 + prior)

    samples = history.get(model_id, [])
    if samples:
        per_cycle = median(samples)
        used_history = True
        n_samples = len(samples)
    else:
        # No history for this model → fall back to tier-typical tokens
        # × the price table.
        in_tok, out_tok = _TIER_FALLBACK_TOKENS.get(tier, (10_000, 2_000))
        table = _price_table()
        in_price, out_price = table.get(model_id, (0.0, 0.0))
        per_cycle = (
            (in_tok / 1_000_000.0) * in_price
            + (out_tok / 1_000_000.0) * out_price
        )
        used_history = False
        n_samples = 0

    estimated_usd = per_cycle * cycles
    return TaskCostEstimate(
        task_text=task_text,
        tier=tier,
        model_id=model_id,
        estimated_cycles=cycles,
        estimated_usd=round(estimated_usd, 4),
        used_history=used_history,
        n_historical_cycles=n_samples,
        prior_failures=prior,
    )


def estimate_inbox(
    db: sqlite3.Connection,
    inbox_path: Path,
    *,
    default_tier: str = "haiku",
) -> InboxCostEstimate:
    """Walk every open ``- [ ]`` task and project total spend."""
    tasks = [t for t in parse_inbox(inbox_path) if not t.done]
    history = _per_cycle_costs_by_model(db)
    out = InboxCostEstimate(n_tasks=len(tasks))
    for t in tasks:
        est = estimate_task_cost(
            db, t.text, history=history, default_tier=default_tier,
        )
        out.tasks.append(est)
        out.total_usd += est.estimated_usd
        out.total_cycles += est.estimated_cycles
    out.total_usd = round(out.total_usd, 4)
    return out


# Make this importable from the escalation module for the
# count-prior-failures heuristic without a circular dependency.
__all__ = [
    "TaskCostEstimate",
    "InboxCostEstimate",
    "estimate_task_cost",
    "estimate_inbox",
]
