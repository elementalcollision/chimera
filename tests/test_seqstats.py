"""Pre-written contract test for v43 build-capability — target 3 of 3.

Charter: mind/research/v43-parallel-builds-design.md (parallel fan-out, N=3
independent single-file builds in one soak). Operator-authored, committed to
main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/seqstats.py — so these tests pass, WITHOUT touching chimera/cli.py, the
other two v43 targets, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a
clean assertion failure. Gated by CHIMERA_V40_GATE.
"""

from __future__ import annotations

import pytest


def _fns():
    try:
        from chimera.seqstats import dedupe_stable, running_max
    except ImportError as exc:
        pytest.fail(f"chimera.seqstats not importable: {exc}")
    return running_max, dedupe_stable


# ── running_max: cumulative maxima ─────────────────────────────────

def test_running_max_basic():
    running_max, _ = _fns()
    assert running_max([3, 1, 4, 1, 5]) == [3, 3, 4, 4, 5]


def test_running_max_edges():
    running_max, _ = _fns()
    assert running_max([]) == []
    assert running_max([5]) == [5]
    assert running_max([1, 2, 2, 1]) == [1, 2, 2, 2]


# ── dedupe_stable: drop later dupes, preserve first-seen order ──────

def test_dedupe_stable_basic():
    _, dedupe_stable = _fns()
    assert dedupe_stable([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_dedupe_stable_edges():
    _, dedupe_stable = _fns()
    assert dedupe_stable([]) == []
    assert dedupe_stable([1, 1, 1]) == [1]
    assert dedupe_stable([4, 5, 6]) == [4, 5, 6]
