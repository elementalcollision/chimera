# ADR 0056 — Per-model + time-series fan-out telemetry (v4.34)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0055](./0055-tool-fanout-telemetry.md) (v4.33) shipped global fan-out telemetry but explicitly
deferred two views: per-model breakdown ("which model actually emits
parallel batches?") and a per-cycle trend ("is the agent learning to
parallelise more over time?"). Both are tiny SQL aggregations on the
data we already collect.

## Decision

Two new TS readers + extension of the existing `ToolFanoutWidget`.
No schema changes.

### Readers ([control-plane/lib/db.ts](control-plane/lib/db.ts))

- `toolFanoutByModel(limit=8)` — groups `api_calls` by `model_id`,
  returns `{model_id, total, parallel, parallel_share, avg_fanout}`
  ordered by total desc.
- `toolFanoutHistory({bucket_size=5, n_buckets=12})` — buckets
  `(cycle, tool_uses_count)` rows into contiguous cycle windows
  oldest-first. Returns `{cycle_bucket_start, cycle_bucket_end,
  total, parallel}`.

### Widget

`ToolFanoutWidget` now accepts optional `byModel` and `history`
props. Renders below the existing distribution:

- **Sparkline** of `parallel / total` per cycle bucket, with a
  reference line at 25% so the operator can see the share rising
  past that threshold.
- **Per-model row list** showing `model_id`, `avg N.NN` fan-out, and
  the percent-parallel column color-graded (mint-ink at ≥50%, fg-2
  at ≥25%, fg-3 below).

Tile resized to `6×6` (was `6×4`) to fit the added rows.

## Tests

TypeScript typecheck clean. No new Python tests — readers are pure
TS aggregation over schema already exercised by v4.33.

Full suite: 535 passing (unchanged).

## Non-goals

- **Server-side caching.** Each render reads the rows fresh; the
  query is small enough not to need a cache.
- **Cost-per-fanout correlation.** Linking fan-out width to
  `cost_usd` would be a v4.4x analysis sprint.
