# ADR 0069 — Round-boundary latency instrumentation (v4.50)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0061](./0061-cross-round-parallelism-deferred.md) (v4.40) deferred cross-round tool parallelism on the basis
that we had no data on whether the round boundary was actually the
bottleneck. The concrete next-step it listed was adding
`round_boundary_latency_ms` to `api_calls` so we could measure
before optimizing.

## Decision

Additive column on `api_calls`:

```sql
ALTER TABLE api_calls ADD COLUMN round_boundary_latency_ms INTEGER;
```

`record_api_call(..., round_boundary_latency_ms=)` accepts the
field. ACT's per-round loop captures `time.perf_counter()` after
the parallel tool-dispatch `gather` completes, and stamps the
elapsed time on the NEXT round's record. The first round of any
task has no prior boundary → stored as NULL.

What the metric measures, exactly: wall-clock between *last tool's
completion* and *next provider's `complete_with_tools` call dispatch*.
That covers the small amount of bookkeeping ACT does between rounds
(append messages, optional history checks). It does NOT include the
provider's TTFT — that's already `latency_ms` on the same row.

## Dashboard surface

The v4.51 ModelUtilizationWidget shows `p50` and `p95` of the
distribution as a pill at the top, so the operator can see "how much
of ACT's wall-clock is boundary overhead" at a glance.

## Tests

`tests/test_act.py::test_act_records_round_boundary_latency` —
exhausting a fake provider over two rounds, asserts row 0's column
is NULL and row 1's is an int ≥ 0.

Full suite: 570 passing.

## Non-goals

- **Per-tool boundary breakdown.** The metric is whole-round; we
  don't split out "model thinking" vs "tool dispatch overhead" from
  this column.
- **Cross-round speculative execution.** v4.40's actual deferral
  stands. v4.50 is the measurement that decides whether we ever
  reopen it.
