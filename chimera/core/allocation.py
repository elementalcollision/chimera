"""Maximum-entropy (Boltzmann) allocation over candidate sub-tasks (ADR 0172).

Under uncertainty about *which* sub-task is the bottleneck, Jaynes' maximum-
entropy principle says: don't prematurely commit the whole budget to one
branch — spread it as the maximum-entropy distribution consistent with the
known constraints, and concentrate only as evidence accrues. Operationally that
is a **Boltzmann/softmax** allocation of a fixed budget over scored candidates,
governed by a **temperature**: hot early (explore broadly, near-uniform), cooled
as confidence grows (concentrate on the best). This generalises today's flat
caps (≤ 3 proposals, ≤ 6 splits) into a budget that *spreads* when the agent is
unsure and *concentrates* when it is confident
([entropy-graph-subtasking-2026-06-06.md](../../docs/research/entropy-graph-subtasking-2026-06-06.md)
§3a, ranked #6).

This module is the **pure** primitive. It is the most speculative of the six
insertions (it needs a per-candidate value estimate the proposal/split paths do
not yet carry), so it ships default-OFF and is wired only as a conservative,
reversible selection — the temperature-driven stochastic allocation is provided
and tested but left for a deferred caller.
"""

from __future__ import annotations

import math
import os
import random
from typing import Sequence, TypeVar

T = TypeVar("T")

#: Default selection temperature. 0.0 ⇒ deterministic (highest value wins,
#: ties keep original order) — the safe default for the wired split path.
_DEFAULT_TEMP = 0.0


def boltzmann_allocation_enabled() -> bool:
    """Honour ``CHIMERA_BOLTZMANN_ALLOC`` (default: off, ADR 0172).

    Same parsing shape as ``peer_selection_enabled`` (ADR 0167).
    """
    raw = os.environ.get("CHIMERA_BOLTZMANN_ALLOC", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def allocation_temperature() -> float:
    """Honour ``CHIMERA_BOLTZMANN_TEMP`` (default: 0.0 = deterministic)."""
    raw = os.environ.get("CHIMERA_BOLTZMANN_TEMP", str(_DEFAULT_TEMP)).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_TEMP


def softmax(values: Sequence[float], temperature: float = 1.0) -> list[float]:
    """Boltzmann weights over ``values`` at ``temperature``, summing to 1.

    Higher temperature ⇒ flatter (more uniform, more exploratory); lower ⇒
    sharper. ``temperature <= 0`` is the zero-temperature limit: all mass on
    the maximum (split evenly across ties). Empty input ⇒ ``[]``.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    if temperature <= 0.0:
        hi = max(values)
        winners = [1.0 if v == hi else 0.0 for v in values]
        s = sum(winners)
        return [w / s for w in winners]
    # Shift by the max for numerical stability.
    m = max(values)
    exps = [math.exp((v - m) / temperature) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


def anneal_temperature(
    t0: float, *, step: int, rate: float = 0.5, floor: float = 0.0
) -> float:
    """Geometric cooling schedule: ``t0 · rate**step``, floored at ``floor``.

    ``step`` 0 returns ``t0`` (hot); each successive step multiplies by
    ``rate`` (0 < rate < 1) so the schedule cools toward ``floor`` as evidence
    accrues.
    """
    if step < 0:
        step = 0
    return max(floor, t0 * (rate ** step))


def allocate_budget(
    values: Sequence[float], budget: int, *, temperature: float = 1.0
) -> list[int]:
    """Allocate an integer ``budget`` across candidates by Boltzmann weight.

    Largest-remainder apportionment over :func:`softmax` weights, so the result
    sums to exactly ``budget`` (for ``budget >= 0``). At high temperature the
    budget spreads near-uniformly; at low temperature it concentrates on the
    highest-value candidates — the explore→exploit knob.
    """
    n = len(values)
    if n == 0 or budget <= 0:
        return [0] * n
    weights = softmax(values, temperature)
    raw = [w * budget for w in weights]
    floors = [int(math.floor(x)) for x in raw]
    remainder = budget - sum(floors)
    # Hand out the remaining units to the largest fractional parts.
    order = sorted(range(n), key=lambda i: (raw[i] - floors[i], values[i]), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def boltzmann_select(
    items: Sequence[T],
    values: Sequence[float],
    k: int,
    *,
    temperature: float = _DEFAULT_TEMP,
    rng: random.Random | None = None,
) -> list[T]:
    """Select ``k`` of ``items`` by value, preserving original order.

    - ``temperature <= 0`` **or** ``rng is None`` ⇒ **deterministic**: keep the
      ``k`` highest-value items (ties resolved by original position). This is
      the safe wired default — a value-aware replacement for "keep the first k".
    - ``temperature > 0`` with an ``rng`` ⇒ **stochastic**: sample ``k`` without
      replacement with Boltzmann probabilities (exploration).

    The selected items are always returned in their original relative order, so
    downstream consumers see a stable ordering.
    """
    n = len(items)
    if k >= n:
        return list(items)
    if k <= 0:
        return []

    if temperature <= 0.0 or rng is None:
        # Deterministic top-k by value; stable on ties via original index.
        ranked = sorted(range(n), key=lambda i: (values[i], -i), reverse=True)
        chosen = set(ranked[:k])
    else:
        # Weighted sampling without replacement.
        remaining = list(range(n))
        chosen_list: list[int] = []
        for _ in range(k):
            w = softmax([values[i] for i in remaining], temperature)
            pick = rng.choices(range(len(remaining)), weights=w, k=1)[0]
            chosen_list.append(remaining.pop(pick))
        chosen = set(chosen_list)

    return [items[i] for i in range(n) if i in chosen]
