# ADR 0053 — Incremental graph projection (v4.31)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0045](./0045-graph-rebuild-perf.md) (v4.23) cut full rebuild from 12s to 230ms via UNWIND
batching. That's good enough for operator-triggered rebuilds, but
still too costly to run from inside the per-cycle housekeeping
phase: a 500-entity graph paying 230ms every cycle is a 0.2-second
tax for no good reason — most cycles add zero or one entity.

The v4.22 stress-test ADR called out an incremental projection as a
follow-up: "diff-based incremental projection is its own ADR."

## Decision

`GraphStore.update_from_sqlite(sqlite_conn)` — append-only incremental
projection scoped to the two volume-dominant tables:

- **Entity**: query `MATCH (e:Entity) RETURN e.id`, diff against
  SQLite's entity ids, UNWIND-CREATE only the missing ones.
- **TRANSITIONED_TO**: query existing edges by
  `(entity_id, cycle, from_state, to_state)`, diff against SQLite's
  `entity_transitions`, UNWIND-CREATE only the new ones.

Returns counts of rows **added** (not totals). Idempotent — running
it three times with no SQLite changes adds zero rows.

`rebuild_from_sqlite` is unchanged and remains the right call when
mutations/peers/skills/wiki need to be refreshed too (those rows
mutate in place; safely diffing them needs status tracking that's
out of scope here).

### CLI

`chimera graph rebuild --incremental` runs the incremental path.
Plain `chimera graph rebuild` still does the full clear+rebuild.

## Measured (dev box)

500 entities + 1000 transitions, then incremental update:

| Path | Time |
|---|---|
| Full rebuild | 232 ms |
| **Incremental, no SQLite delta** | **55 ms** (~4× faster) |
| **Incremental, +10 entities + 10 transitions** | **72 ms** (~3× faster) |

Wall-clock perf depends on graph size — the diff queries scale with
N, not the delta — but the dominant cost (UNWIND-CREATE of new rows)
scales with the delta. The break-even vs full rebuild is at roughly
half the entity count of new inserts; below that, incremental wins.

## Tests

`tests/test_graph_store.py` — three new tests:

- `test_update_from_sqlite_appends_new_entities` — populate, no-op,
  add one, only diff is appended.
- `test_update_from_sqlite_appends_new_transitions` — entity already
  projected, only the new transition is added.
- `test_update_from_sqlite_is_idempotent` — three repeat calls →
  same row count.

Full suite: 533 passing, 5 skipped (was 530 / 5, +3 new).

## Non-goals

- **Incremental mutation/peer/skill projection.** Those rows mutate
  (status, last-seen). Need a tracked-cursor scheme; left for a
  future ADR.
- **Auto-incremental in the housekeeping phase.** Adding it to the
  loop is straightforward but warrants its own decision about cadence
  (every cycle? every N?). Not in v4.31 scope.
- **Vacuum / GC.** Append-only means archived entities stay
  projected. Compaction is a separate concern.
