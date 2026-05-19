"""Stagnation drift detector — proposal-space drift, orthogonal to behavioral.

Ported from ``autoresearch-unified/tui/orchestrator.py:582 _detect_stagnation``
per ADR 0001 §"Stagnation drift detector". Generic shape: a rolling window
of recent (bucket, kept) outcomes. When one bucket saturates the window with
low success rate, return a nudge string for the next prompt.

Pure module. The orchestrator decides when to call this and what to do with
the result.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class StagnationConfig:
    window: int = 15                       # how many recent items to consider
    max_kept_for_stagnation: int = 2       # stagnation only triggers if kept ≤ this
    bucket_saturation: int = 8             # one bucket must contain at least this many


@dataclass(frozen=True)
class Outcome:
    """A single completed task / experiment."""

    bucket: str           # strategy category, e.g. "shell", "edit", "plan"
    kept: bool            # did the result clear the success bar?


def detect_stagnation(
    history: Iterable[Outcome],
    config: StagnationConfig | None = None,
) -> str | None:
    """Return a nudge string when the recent window shows bucket saturation
    with low success — otherwise ``None``.

    The recipe matches autoresearch's heuristic exactly: take the tail
    ``window`` outcomes; if total kept count is at or below
    ``max_kept_for_stagnation`` AND any single bucket occupies at least
    ``bucket_saturation`` slots, emit a nudge naming the dominant bucket and
    suggesting alternatives.
    """
    cfg = config or StagnationConfig()
    tail = list(history)[-cfg.window :]
    if len(tail) < cfg.window:
        return None  # not enough data yet

    kept = sum(1 for o in tail if o.kept)
    if kept > cfg.max_kept_for_stagnation:
        return None

    counts = Counter(o.bucket for o in tail)
    dominant, dominant_count = counts.most_common(1)[0]
    if dominant_count < cfg.bucket_saturation:
        return None

    alternatives = sorted(b for b in counts if b != dominant)
    alt_hint = ", ".join(alternatives) if alternatives else "a different strategy"
    return (
        f"Heads up: {dominant_count}/{cfg.window} recent attempts were "
        f"{dominant!r} with only {kept} kept. Consider trying {alt_hint} instead."
    )
