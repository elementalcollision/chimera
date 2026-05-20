# ADR 0054 — Auto-incremental graph in housekeeping (v4.32)

**Status:** Accepted (2026-05-19)

## Context

v4.31 shipped `GraphStore.update_from_sqlite` — 3–4× faster than a
full rebuild for typical small-delta cycles. [ADR 0053](./0053-incremental-projection.md) called out
"adding it to the loop is straightforward but warrants its own
decision about cadence" as a non-goal.

The right cadence is the simplest one: once per cycle, in the
existing housekeeping phase. That phase already runs auto-archive
and is budgeted 500ms — plenty of headroom for a 55ms incremental
graph update.

## Decision

`_phase_housekeeping` now performs three things in sequence:

1. Auto-archive stale DEPRECATED entities (v4.24).
2. **NEW:** incremental graph projection via `update_from_sqlite`.
3. Record activity + log line summarising both.

Env-gated by `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED` (set to 1/true/yes
to skip — useful when the operator wants a long-running graph
batch outside the cycle path).

The housekeeping `agent_activity_log` row's `details` field now
includes `graph_added`, `graph_entity`, `graph_transitioned_to`
when non-zero — feeding any future "what did housekeeping touch"
audit.

### Cadence semantics

Housekeeping runs FIRST in each cycle, so the graph picks up
entities created in the PREVIOUS cycle's WAKE/PLAN/ACT phases. The
bootstrap plan from cycle 1 lands in the graph during cycle 2's
housekeeping. This is intentional — keep cycle 1's mutating window
free of side-effects, then sweep up.

## Tests

`tests/test_loop_memory.py`:

- `test_housekeeping_appends_to_graph_incrementally` — two cycles
  produce ≥1 entity in the graph (the bootstrap plan).
- `test_housekeeping_disabled_skips_graph_update` — with
  `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED=1` set, graph stays empty.

Full suite: 533 passing.

## Non-goals

- **Mutating-row projections (peers, mutations, skills).** Still
  need a full `chimera graph rebuild` to refresh those.
- **Adaptive cadence.** Future ADRs may skip the update when the
  cycle is producing no new entities (already cheap: 55ms no-op).
