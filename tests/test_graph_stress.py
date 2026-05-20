"""v4.22 — LadybugDB graph stress smoke test.

Runs the stress scenario at a small scale (50 entities) so it fits in
the default test suite. Confirms rebuild succeeds, restart durability
holds, and query latencies are non-negative numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.scenarios import run_graph_stress


def test_graph_stress_smoke(tmp_path: Path):
    result = run_graph_stress(
        sqlite_path=tmp_path / "chimera.db",
        graph_path=tmp_path / "chimera.graph",
        n_entities=50,
        transitions_each=2,
        repeat_queries=3,
    )

    assert result.ok, f"stress failed: {result.failures}"
    assert result.rebuild_counts.get("Entity") == 50
    # 50 entities * 2 transitions each.
    assert result.rebuild_counts.get("TRANSITIONED_TO") == 100
    # All four representative queries fired.
    labels = {q.label for q in result.query_timings}
    assert {"count_entities", "filter_kind_plan",
            "count_transitions", "filter_transition_target"}.issubset(labels)
    # Restart durability — graph re-opens with the same Entity count.
    assert result.restart_count_match


def test_graph_stress_latency_is_measured(tmp_path: Path):
    result = run_graph_stress(
        sqlite_path=tmp_path / "chimera.db",
        graph_path=tmp_path / "chimera.graph",
        n_entities=20,
        transitions_each=1,
        repeat_queries=5,
    )
    assert result.ok
    for q in result.query_timings:
        assert q.p50_ms >= 0
        assert q.p95_ms >= q.p50_ms
        assert len(q.latency_ms) == 5
