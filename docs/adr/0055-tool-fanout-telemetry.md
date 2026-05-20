# ADR 0055 — Tool-fanout telemetry (v4.33)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0040](./0040-parallel-tool-dispatch.md) (v4.18) shipped parallel tool dispatch but the only proof
that the model is actually fanning out is the log line inside ACT.
We had no way to look at a dashboard and see what fraction of ACT
rounds emit parallel batches, or whether a model regression has
silently dropped fan-out back to serial.

## Decision

A small telemetry column + reader + widget. No new tables.

### Schema

`api_calls.tool_uses_count INTEGER` (nullable). Idempotent additive
migration in `init_schema`. 0 = pure text reply, 1 = single tool
call, 2+ = parallel batch. Recorded for every successful
`complete_with_tools` response.

### Recorder

`record_api_call(..., tool_uses_count=...)` accepts the new field;
ACT supplies `len(response.tool_uses or [])` at the call site.
Errors don't set the column (NULL).

### Dashboard

- `control-plane/lib/db.ts::toolFanout()` aggregates non-null rows
  with `tool_uses_count > 0` into:
  - `serial` (1), `parallel_2`, `parallel_3_plus`
  - `max_fanout`, `parallel_share` (= parallel / total)
- New `ToolFanoutWidget` (group: cost): serif headline shows
  `parallel_share` as a percentage, three BarRows show the
  distribution, max_fanout printed alongside.
- Chip toning on the page tile: mint with "% parallel" when share
  ≥ 25% (otherwise unchipped — meaningful only when there's
  evidence of the model actually using the capability).

## Tests

`tests/test_act.py::test_act_dispatches_multiple_tool_uses_in_parallel`
extended: after the parallel-call assertion, query
`SELECT tool_uses_count FROM api_calls` and verify the series is
`[2, 0]` — first response had two tool_uses, final response was
pure text.

TypeScript typecheck clean. Full suite: 535 passing.

## Non-goals

- **Time-series widget.** Snapshot histogram only. Trending fan-out
  over cycles is a v4.3x sprint.
- **Per-model breakdown.** All providers aggregated. Per-model
  histograms would help diagnose a single-model regression but
  aren't needed for the headline question ("is the agent using
  parallelism at all?").
