"""Branching-process budgets for sub-tasking fan-out (ADR 0171).

Chimera's self-decomposition is a Galton–Watson branching process: each task
spawns a random number of children, and with mean offspring μ > 1 and unbounded
depth the work tree **explodes** — the cost-runaway the fixed `max_depth` and
the ADR 0072 cost caps exist to prevent. Those caps are a *crude*
branching-process control; this module is the principled primitive
([entropy-graph-subtasking-2026-06-06.md](../../docs/research/entropy-graph-subtasking-2026-06-06.md)
§2c, ranked #3).

The one genuinely **uncapped** place is parallel tool fan-out (`core/act.py`):
`asyncio.gather` over *whatever the model emits* — unbounded width. A branching
lens caps it: the marginal value of the w-th simultaneous probe has diminishing
returns, so stop widening past a budget. This module supplies the pure split
plus the subcriticality helpers; the cap is wired into ACT behind a default-OFF
flag, so behaviour is byte-identical until opted in.
"""

from __future__ import annotations

import os

#: Default ceiling on simultaneous tool calls in one ACT round. Chosen well
#: above normal batches (1–3) so it only ever trims pathological fan-out.
_DEFAULT_MAX_WIDTH = 8


def fanout_budget_enabled() -> bool:
    """Honour ``CHIMERA_FANOUT_BUDGET`` (default: off, ADR 0171).

    Same parsing shape as ``peer_selection_enabled`` (ADR 0167).
    """
    raw = os.environ.get("CHIMERA_FANOUT_BUDGET", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def fanout_max_width() -> int:
    """Honour ``CHIMERA_FANOUT_MAX_WIDTH`` (default: 8, ADR 0171).

    Always ≥ 1 so the round can still make progress even on a bad value.
    """
    raw = os.environ.get("CHIMERA_FANOUT_MAX_WIDTH", str(_DEFAULT_MAX_WIDTH)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_WIDTH


def fanout_split(width: int, max_width: int) -> tuple[int, int]:
    """Split a fan-out of ``width`` calls into ``(dispatch, skip)`` counts.

    Dispatch the first ``max_width`` (the model's order is its priority); defer
    the rest. ``max_width`` is floored at 1. Never returns a negative skip.
    """
    cap = max(1, max_width)
    dispatch = min(width, cap)
    return dispatch, max(0, width - cap)


def is_subcritical(mu: float, p_continue: float) -> bool:
    """Subcriticality test for a branching process: ``μ · p_continue < 1``.

    ``mu`` is the mean number of children a task spawns; ``p_continue`` is the
    probability a child itself spawns. Below 1 the expected tree size is
    finite (the cost-bounded regime); at or above 1 it can explode.
    """
    return (mu * p_continue) < 1.0


def expected_branching_total(mu: float, depth: int) -> float:
    """Expected total nodes of a depth-bounded branching tree: Σ_{d=0}^{depth} μ^d.

    The geometric series that the flat `max_depth` cap bounds bluntly. Useful
    for reasoning about "deeper when each level is cheap, shallow when
    expensive" — the principled replacement for a constant depth.
    """
    if depth < 0:
        return 0.0
    if mu == 1.0:
        return float(depth + 1)
    return (mu ** (depth + 1) - 1.0) / (mu - 1.0)


def subcritical_depth_budget(mu: float, *, hard_cap: int) -> int:
    """Largest depth whose expected work stays bounded, capped at ``hard_cap``.

    For μ ≤ 1 the process is already (sub)critical at any depth, so the answer
    is ``hard_cap``. For μ > 1 each extra level multiplies expected work by μ,
    so cheaper branching (smaller μ) earns more depth — but never beyond
    ``hard_cap``, which preserves the ADR 0072 boundedness guarantee.
    """
    cap = max(0, hard_cap)
    if mu <= 1.0:
        return cap
    # Allow depth up to where μ^depth stays within one order of magnitude of
    # work growth (a conservative budget), bounded by hard_cap.
    import math

    budget = int(math.log(10.0, mu)) if mu > 1.0 else cap
    return max(1, min(cap, budget))
