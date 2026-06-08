"""Entropy observability signals (ADR 0170).

Several signals Chimera already half-measures *are* entropies — naming them
yields continuous diagnostics where today there are only exact-match
thresholds. This module is the shared primitive plus the named signals the
investigation
([entropy-graph-subtasking-2026-06-06.md](../../docs/research/entropy-graph-subtasking-2026-06-06.md)
§3d, ranked #5) calls out:

- **Tool-use entropy** H(tool distribution) per cycle. Low H = fixation — a
  degenerate-loop *precursor*, earlier than the exact-repeat detector in
  ``act.py``; high-but-unproductive H = thrashing.
- **Proposal diversity** = cluster entropy over ``dedup.cluster_key``; a
  low-entropy proposal batch is redundant before any single pair is an exact
  fingerprint collision.
- **Stagnation** = the *falling* entropy of the KFM-transition / activity
  distribution over time. Shannon entropy of the transition counts is a
  principled, continuous stagnation metric for the existing composite drift.

All functions are **pure** and always computable (so they can be unit-tested
and previewed); the ``CHIMERA_ENTROPY_SIGNALS`` flag gates whether callers log
them, keeping behaviour byte-identical until opted in.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from typing import Hashable, Iterable

from ..proposals.dedup import cluster_key, fingerprint


def entropy_signals_enabled() -> bool:
    """Honour ``CHIMERA_ENTROPY_SIGNALS`` (default: off, ADR 0170).

    Same parsing shape as ``peer_selection_enabled`` (ADR 0167). The signal
    functions are always computable; this only gates logging/emission.
    """
    raw = os.environ.get("CHIMERA_ENTROPY_SIGNALS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def shannon_entropy(counts: Iterable[float]) -> float:
    """Shannon entropy in **bits** of a distribution given by ``counts``.

    Counts need not be normalised; non-positive counts are ignored. Returns
    0.0 for an empty or single-category distribution.
    """
    weights = [float(c) for c in counts if c > 0]
    total = sum(weights)
    if total <= 0 or len(weights) <= 1:
        return 0.0
    h = 0.0
    for w in weights:
        p = w / total
        h -= p * math.log2(p)
    return h


def normalized_entropy(counts: Iterable[float]) -> float:
    """Shannon entropy scaled to ``[0, 1]`` by dividing by ``log2(k)``.

    ``k`` is the number of non-empty categories. 1.0 = perfectly uniform
    (maximum diversity), 0.0 = all mass on one category (fixation). Returns
    0.0 when there are fewer than two non-empty categories.
    """
    weights = [float(c) for c in counts if c > 0]
    k = len(weights)
    if k <= 1:
        return 0.0
    return shannon_entropy(weights) / math.log2(k)


def entropy_of_labels(labels: Iterable[Hashable]) -> float:
    """Normalized entropy over a sequence of categorical labels."""
    counts = Counter(labels)
    return normalized_entropy(counts.values())


def tool_use_entropy(tool_names: Iterable[str]) -> float:
    """Normalized entropy of the per-cycle tool-name distribution.

    Low ⇒ the agent is fixating on one tool (a degenerate-loop precursor);
    high ⇒ broad tool use. Empty / single-call cycles return 0.0.
    """
    return entropy_of_labels(tool_names)


def proposal_diversity(texts: Iterable[str]) -> float:
    """Normalized cluster entropy over a batch of proposal texts.

    Each text is labelled by its ``(basename, verb)`` cluster key (falling back
    to its content fingerprint when no cluster key is extractable), then the
    entropy of that label distribution is taken. Low ⇒ the batch is
    semantically redundant (many proposals collapse to the same intent) and is
    a candidate to regenerate; high ⇒ a diverse batch.
    """
    labels: list[Hashable] = []
    for t in texts:
        bn, vb = cluster_key(t)
        labels.append((bn, vb) if (bn and vb) else fingerprint(t))
    return entropy_of_labels(labels)


def transition_entropy(transitions: Iterable[tuple[Hashable, Hashable]]) -> float:
    """Normalized entropy of a KFM/activity transition distribution.

    ``transitions`` is a sequence of ``(from_state, to_state)`` pairs. A high
    value means the agent is moving through varied states; a value that *falls*
    over successive windows is stagnation — the formal reading of the existing
    composite drift's stagnation component.
    """
    return entropy_of_labels(tuple(t) for t in transitions)
