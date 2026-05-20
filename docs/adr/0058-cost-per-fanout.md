# ADR 0058 — Cost-per-fanout correlation (v4.37)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0056](./0056-fanout-by-model-and-history.md) (v4.34) added per-model and per-cycle views of tool fan-out
but didn't connect fan-out to cost. That connection is the
operationally interesting one: a 2-fanout response delivers 2 tool
calls for ~1 API call's worth of input tokens, so the cost-per-
useful-action drops as fan-out widens. Without the data on screen,
the operator can't see whether parallel batches are actually saving
money or whether long parallel batches are just over-emitting.

## Decision

Compute cost per fan-out bucket from the tokens already in
`api_calls` × `effectivePrices()`. No new schema, no new readers
beyond the row dump.

### Aggregator ([control-plane/lib/cost.ts](control-plane/lib/cost.ts))

`costByFanout(rows)` returns three `FanoutCostBucket`s for `1` /
`2` / `3+`:

- `calls`, `toolCalls`, `totalCost`
- `costPerCall` — `totalCost / calls`
- `costPerToolCall` — `totalCost / toolCalls` — the "useful action"
  unit cost.

### Reader

`fanoutCostRows()` in `lib/db.ts` returns `(model_id, input_tokens,
output_tokens, tool_uses_count)` for non-error rows with
`tool_uses_count > 0`.

### Widget

`ToolFanoutWidget` extended with an optional `costByFanout` prop.
Adds a section showing `$/call vs $/tool-call` per bucket, with a
right-aligned `-NN%` indicator when the parallel bucket's
cost-per-tool-call is meaningfully below the serial cost-per-call.
Mint-ink at ≥30% savings.

## Tests

TypeScript typecheck clean. No new Python tests — pure TS over
existing schema.

Full suite: 537 passing (unchanged from v4.35).
