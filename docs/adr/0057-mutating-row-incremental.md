# ADR 0057 — Incremental projection for mutating rows (v4.35)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0053](./0053-incremental-projection.md) (v4.31) shipped `update_from_sqlite` as an append-only
projection — great for entities + transitions, which never mutate.
Mutations and peers do mutate: a mutation row's `status` flips from
`pending` to `approved` to `applied`; peer entries get re-registered
with new `registered_at`. The append-only path was stuck — it could
add new mutations but couldn't capture status changes.

The v4.31 / v4.32 ADRs both noted this as a non-goal pending its
own decision.

## Decision

Extend `GraphStore.update_from_sqlite` with two new internal helpers
that do **replace-in-place** for the small mutating tables:

- `_replace_mutations(sqlite_conn)` — `MATCH (m:Mutation) DETACH
  DELETE m` (drops PROPOSED/ACTIVATED edges automatically), then
  UNWIND CREATE from SQLite + re-project the edges via the existing
  `_project_mutation_edges`.
- `_replace_peers()` — same shape for Peer + TRUSTED.

Both run by default; flagged off via `include_mutations=False` and
`include_peers=False` kwargs for callers that want strict append-only
semantics.

Skills and WikiDocs are NOT touched — they require filesystem-scan
work (`mind/`, `dynamic_skills_dir()`) that's better-suited to an
operator-triggered full `chimera graph rebuild`.

### Why detach-delete rather than diff-and-update

Kuzu 0.10 doesn't have a portable MERGE on properties; per-row
property updates require MATCH-then-SET dispatch, which is N driver
calls. The mutation + peer tables are small (operator-scale —
typically <100 rows each), so a single DETACH DELETE + UNWIND CREATE
beats any per-row SET pattern on wall-clock and complexity.

## Tests

`tests/test_graph_store.py`:

- `test_update_picks_up_mutation_status_flip` — create pending →
  update → mark_applied → update; graph reflects `status='applied'`
  with no duplicate row.
- `test_update_with_mutations_disabled_skips_replace` — caller can
  opt out; mutation stays at the old projected status.

Full suite: 537 passing, 5 skipped (was 535 / 5, +2 new).

## Non-goals

- **Skill / wiki incremental.** Filesystem-scan heavy; operator
  rebuild path remains canonical for those.
- **api_calls projection.** Not currently in the graph as a node;
  not in scope.
- **Cost model.** Replace-in-place is O(M) per update where M is
  small. If mutations grow to thousands a future ADR can switch to
  per-row SET on changed status.
