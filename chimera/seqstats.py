"""Cumulative running maximum and stable deduplication.

Provenance: authored by Chimera autonomously during the v43 parallel-build
soak (R3, ladder rung 4, N=3), branch chimera-soak/v43-trio-2026-05-30-0052,
agent commit d09e88f. Landed verbatim. Capstone
mind/research/v43-trio-capstone.md.
"""

from __future__ import annotations


def running_max(values: list[float]) -> list[float]:
    """Return cumulative maxima: each position holds the max seen so far."""
    if not values:
        return []
    result = []
    current = values[0]
    for v in values:
        if v > current:
            current = v
        result.append(current)
    return result


def dedupe_stable(values: list) -> list:
    """Drop later duplicates, preserving first-seen order."""
    seen = set()
    result = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
