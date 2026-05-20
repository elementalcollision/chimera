# ADR 0070 — Model utilization (engine pressure) widget (v4.51)

**Status:** Accepted (2026-05-19)

## Context

Cycle 13's PLAN-phase reflection said `"deepseek flash engine ran
hard today—235 calls"`. That's a real signal of model-pressure that
never made it to the dashboard. Operators had no way to see "this
model is being hammered" until reviewing chronicle text by hand.

## Decision

Two new TS readers in `lib/db.ts` and one widget.

### `modelUtilization(opts?)`

Returns per-model rows with `total`, `last_24h`, `last_hour`,
`peak_per_cycle`, and a `series[]` of per-cycle counts over the
last N cycles. Sorted by total desc. Uses a CTE to compute
peak-per-cycle without a CROSS JOIN.

### `roundBoundaryStats()`

Returns `{samples, p50_ms, p95_ms, mean_ms, max_ms}` from the v4.50
`round_boundary_latency_ms` column. Used by the same widget as a
header pill.

### `ModelUtilizationWidget`

Renders:
- **Headline**: total api calls + top peak/cycle across all models.
- **Pill** (right-aligned): round-boundary p50/p95 in ms (when v4.50 data exists).
- **Row list**: per model — name, total, calls/hour, peak/cycle, sparkline of recent activity.
- **Tone**: mint < 30 peak/cycle; amber ≥ 30; peach ≥ 100.

Tile chip warns "high volume" when any model crosses peak_per_cycle ≥ 100.

### Page placement

Wired at `(x=6, y=15, w=6, h=6)` alongside the Tool-fanout widget,
in the **cost** group.

## Tests

TypeScript typecheck clean. No new Python tests — pure TS aggregation
over schema already exercised by v4.33 and v4.50.

Full suite: 570 passing.

## Non-goals

- **Engine attribution.** We show per-`model_id`, not per-engine.
  Mapping engine → model_id requires either an explicit join column
  on `api_calls` or a side journal. Future work.
- **Per-phase utilization.** PLAN-phase calls vs ACT-phase calls
  aren't currently distinguishable in the schema.
