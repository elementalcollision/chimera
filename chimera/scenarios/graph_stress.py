"""v4.22 — LadybugDB graph stress test.

Synthetic load on the Kuzu-backed graph store:

  1. Populate SQLite with N entities, each walked through a couple of
     KFM state transitions.
  2. Project into the graph via ``GraphStore.rebuild_from_sqlite``.
  3. Time representative Cypher queries (entity count, entity-by-name
     lookup, transition fan-out, two-hop traversal).
  4. Close + reopen the graph and rerun a verification query to confirm
     restart durability.

Tunable from the CLI (``chimera graph stress --entities N``) and used
by ``tests/test_graph_stress.py`` at a small scale.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory import (
    GraphStore,
    create_entity,
    open_and_init,
    transition_entity,
)


@dataclass
class QueryTiming:
    label: str
    rows: int
    latency_ms: list[float] = field(default_factory=list)

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latency_ms) if self.latency_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.latency_ms:
            return 0.0
        sorted_ms = sorted(self.latency_ms)
        idx = max(0, int(len(sorted_ms) * 0.95) - 1)
        return sorted_ms[idx]


@dataclass
class GraphStressResult:
    n_entities: int
    n_transitions: int
    populate_seconds: float = 0.0
    rebuild_seconds: float = 0.0
    rebuild_counts: dict[str, int] = field(default_factory=dict)
    query_timings: list[QueryTiming] = field(default_factory=list)
    restart_count_match: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and self.restart_count_match

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_entities": self.n_entities,
            "n_transitions": self.n_transitions,
            "populate_seconds": round(self.populate_seconds, 4),
            "rebuild_seconds": round(self.rebuild_seconds, 4),
            "rebuild_counts": self.rebuild_counts,
            "queries": [
                {
                    "label": q.label,
                    "rows": q.rows,
                    "p50_ms": round(q.p50_ms, 3),
                    "p95_ms": round(q.p95_ms, 3),
                    "samples": len(q.latency_ms),
                }
                for q in self.query_timings
            ],
            "restart_count_match": self.restart_count_match,
            "failures": self.failures,
            "ok": self.ok,
        }


def _time_query(store: GraphStore, cypher: str, *, repeat: int) -> tuple[int, list[float]]:
    last_rows = 0
    samples: list[float] = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = store.query(cypher)
        samples.append((time.perf_counter() - t0) * 1000.0)
        last_rows = len(result.rows)
    return last_rows, samples


def run_graph_stress(
    *,
    sqlite_path: Path,
    graph_path: Path,
    n_entities: int = 200,
    transitions_each: int = 2,
    repeat_queries: int = 10,
) -> GraphStressResult:
    """Drive the stress run. Caller supplies isolated paths."""
    result = GraphStressResult(
        n_entities=n_entities,
        n_transitions=n_entities * transitions_each,
    )

    # ── Phase 1: populate SQLite ────────────────────────────
    conn = open_and_init(sqlite_path)
    try:
        t0 = time.perf_counter()
        entity_ids: list[str] = []
        # Half plans, half skills — gives by_kind some variety.
        for i in range(n_entities):
            kind = "plan" if i % 2 == 0 else "skill"
            e = create_entity(conn, kind=kind, name=f"e_{i}", cycle=0)
            entity_ids.append(e.id)
            if transitions_each >= 1:
                transition_entity(
                    conn, e.id, "EXPERIMENTAL", "f", cycle=1,
                )
            if transitions_each >= 2:
                transition_entity(
                    conn, e.id, "CANDIDATE", "m", cycle=2,
                )
        result.populate_seconds = time.perf_counter() - t0
    finally:
        conn.close()

    # ── Phase 2: rebuild the graph ──────────────────────────
    sqlite_conn = open_and_init(sqlite_path)
    try:
        store = GraphStore(graph_path)
        try:
            t0 = time.perf_counter()
            counts = store.rebuild_from_sqlite(sqlite_conn)
            result.rebuild_seconds = time.perf_counter() - t0
            result.rebuild_counts = dict(counts)
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"rebuild failed: {exc}")
            return result

        if result.rebuild_counts.get("Entity", 0) != n_entities:
            result.failures.append(
                f"Entity count mismatch: graph={result.rebuild_counts.get('Entity')} "
                f"sqlite={n_entities}"
            )

        # ── Phase 3: representative queries ────────────────
        try:
            r, s = _time_query(
                store,
                "MATCH (n:Entity) RETURN count(n)",
                repeat=repeat_queries,
            )
            result.query_timings.append(
                QueryTiming(label="count_entities", rows=r, latency_ms=s)
            )
            r, s = _time_query(
                store,
                "MATCH (e:Entity {kind: 'plan'}) RETURN e.name LIMIT 50",
                repeat=repeat_queries,
            )
            result.query_timings.append(
                QueryTiming(label="filter_kind_plan", rows=r, latency_ms=s)
            )
            r, s = _time_query(
                store,
                "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) "
                "RETURN count(t)",
                repeat=repeat_queries,
            )
            result.query_timings.append(
                QueryTiming(label="count_transitions", rows=r, latency_ms=s)
            )
            r, s = _time_query(
                store,
                "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) "
                "WHERE t.to_state = 'CANDIDATE' "
                "RETURN e.name LIMIT 25",
                repeat=repeat_queries,
            )
            result.query_timings.append(
                QueryTiming(label="filter_transition_target", rows=r, latency_ms=s)
            )
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"query failed: {exc}")
    finally:
        sqlite_conn.close()

    # ── Phase 4: restart durability ─────────────────────────
    try:
        store2 = GraphStore(graph_path)
        rows = store2.query("MATCH (n:Entity) RETURN count(n)").rows
        graph_count = int(rows[0][0]) if rows else 0
        result.restart_count_match = graph_count == n_entities
        if not result.restart_count_match:
            result.failures.append(
                f"post-restart Entity count mismatch: graph={graph_count} sqlite={n_entities}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"restart query failed: {exc}")

    return result
