# ADR 0044 — LadybugDB graph stress test (v4.22)

**Status:** Accepted (2026-05-19)

## Context

LadybugDB (the Kuzu-backed graph store from v2.10 / [ADR 0015](./0015-graph-store.md)) has only
ever been exercised at unit scale — `tests/test_graph_store.py` runs
with 5–10 entities and ~20 edges. We have no evidence of how it
behaves at the scale Chimera's own ontology accumulates (hundreds of
entities, thousands of transitions, months of activity log), and no
data on rebuild latency, query latency, or restart durability under
load.

## Decision

A scripted stress scenario in `chimera/scenarios/graph_stress.py`:

1. **Populate** SQLite with N entities (default 500), half plans /
   half skills, each walked through `NEW → EXPERIMENTAL → CANDIDATE`.
2. **Rebuild** the graph via `GraphStore.rebuild_from_sqlite` and
   measure wall-clock.
3. **Query** four representative shapes 10× each with `time.perf_counter`:
   - `count_entities` — global aggregate
   - `filter_kind_plan` — predicate + LIMIT
   - `count_transitions` — relationship aggregate
   - `filter_transition_target` — predicate on edge property
4. **Restart durability** — close the GraphStore, re-open at the same
   path, query the Entity count, assert it matches.

Returns a structured `GraphStressResult` with timings and rebuild
counts. CLI: `chimera graph stress [--entities N] [--repeat M] [--json]`.

## Measured baselines (Mac, dev box)

500 entities × 2 transitions each = 1000 edges:

| Phase | Time |
|---|---|
| SQLite populate | 0.10 s |
| Graph rebuild | **12.09 s** |
| Query `count_entities` | p50 0.53ms / p95 0.71ms |
| Query `filter_kind_plan` (50 rows) | p50 0.36ms / p95 0.37ms |
| Query `count_transitions` | p50 0.50ms / p95 0.75ms |
| Query `filter_transition_target` (25 rows) | p50 0.64ms / p95 0.77ms |

### Findings

- **Queries are fast.** Sub-millisecond at this scale; Kuzu's
  property-graph indexing comfortably handles the ontology shapes the
  dashboard cares about.
- **Rebuild is the bottleneck.** 12s for 500 entities + 1000
  transitions is much worse than it should be. The rebuild walks all
  six projections sequentially via the Python driver. This becomes a
  problem when CHIMERA_AUTO_GRAPH_REBUILD fires during a normal cycle.
  Filed as a follow-up: batched insert + projected-table swap, not in
  scope for v4.22.
- **Restart durability is solid.** Close + re-open produces the same
  Entity count every run. No WAL corruption observed.
- **Filesystem bleed.** The rebuild reads real `~/.chimera/peers/`
  and `mind/` directories regardless of the SQLite path, so a stress
  run on a fresh DB still produces Peer + WikiDoc edges. Not a bug —
  the projection is "filesystem + SQLite" by design — but worth
  knowing when interpreting results.

## Tests

- `tests/test_graph_stress.py::test_graph_stress_smoke` — 50 entities,
  verifies counts + restart match.
- `tests/test_graph_stress.py::test_graph_stress_latency_is_measured`
  — confirms p50/p95 are well-formed numbers.
- Full suite: 517 passing, 5 skipped (was 515 / 5, +2 new).

## Non-goals

- **Performance fix for rebuild.** Filed as a follow-up. The stress
  scenario is observation infrastructure; remediation gets its own ADR.
- **Concurrent access.** Kuzu is single-writer; the scenario is
  serial. Multi-process / multi-cycle contention is its own audit.
- **TRUSTED / ACTIVATED / DEPENDS_ON projections.** The synthetic
  load doesn't seed mutations or skill-AST imports, so those edge
  counts are zero. Adding them is a small follow-up.
