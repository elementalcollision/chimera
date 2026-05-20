# ADR 0045 — Graph rebuild perf via UNWIND batching (v4.23)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0044](./0044-ladybug-stress-test.md) found the LadybugDB rebuild taking 12.09s for 500 entities +
1000 transitions. The bottleneck was obvious: every CREATE was a
separate `kuzu.Connection.execute()` call. 1500+ driver round trips
per rebuild, each paying parser + planner overhead. This was an
operational footgun — if the housekeeping or doctor verb triggers a
rebuild during a normal cycle, the loop stalls for double-digit
seconds.

## Decision

Replace per-row `CREATE` loops with single `UNWIND $rows AS row …
CREATE` calls, one per node/rel table. The driver receives one list
of dicts per table; Kuzu fans the create out internally.

Applied to all six projections:

- Entities, Mutations, ApiCalls — node tables
- TRANSITIONED_TO — relation table with `MATCH (e:Entity) … CREATE`
- Peers — node table
- Mutation edges (PROPOSED, ACTIVATED) — batched MATCH/CREATE
- Trust edges (TRUSTED) — batched MATCH/CREATE
- Skills, DEPENDS_ON, USES_TOOL, WikiDoc, REFERENCES — node + rel
  batches

The clear-then-rebuild semantics are unchanged. `clear_all()` still
uses per-table DELETE since it's already a single statement per table.

## Measured

500 entities × 2 transitions, dev box, post-UNWIND:

| Phase | Before | After |
|---|---|---|
| Rebuild | 12.09 s | **0.21 s** |
| Speedup | — | **57×** |

Query latencies (p50/p95) unchanged — sub-millisecond.

## Tests

- Existing `tests/test_graph_store.py` and `tests/test_graph_stress.py`
  unchanged — they verify behavior, not perf, and they still pass.
- Full suite: 517 → 522 passing, 5 skipped.

## Non-goals

- **Concurrency.** Kuzu remains single-writer; UNWIND just batches
  the writes already going to one connection.
- **Incremental projection.** This is still a full clear + rebuild.
  A diff-based incremental projection is its own ADR.
