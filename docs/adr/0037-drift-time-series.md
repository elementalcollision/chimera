# ADR 0037 — Drift composite time series + sparkline (v4.15)

**Status:** Accepted (2026-05-19)

## Context

The ADR 0002 drift composite is the single highest-signal "is the
agent healthy?" number. Until v4.15 only the **last** composite was
recorded — in `HEARTBEAT.md` frontmatter — so the dashboard could
show the current value but never the trend. A 0.31 reading is
worrying in isolation and meaningless without context; the same
0.31 after a slow climb from 0.10 is a totally different signal
than 0.31 after a spike from 0.50.

## Decision

### Append-only drift log

New module `chimera/core/drift_log.py`:

- `record_drift(cycle, composite_score, severity, action, reason)`
  appends one JSONL row to `state/drift_log.jsonl`.
- `list_drift(limit=N)` reads newest-last.
- Pure file I/O; no DB dependency.

`ChimeraLoop._phase_flush` calls `record_drift` whenever a drift
**reading** exists (i.e. we have ≥3 observations and computed a real
composite). Stagnation-only nudges that don't carry a composite are
skipped — the file would record a stream of 0.0s otherwise.

Failures are caught + logged; the file is best-effort.

### Dashboard sparkline

- `lib/graph.ts::readDriftLog(limit)` reader.
- New `components/widgets/DriftSparklineWidget.tsx` renders an
  inline-SVG polyline of the last N composites. No chart library
  dependency. Latest value displayed with severity-coloured text
  (green/amber/red). Two dashed guides at 0.20 (warning) and 0.30
  (lockdown) provide threshold context.
- Wired into the canvas page next to Phase timings (6w × 4h).

## Why inline SVG, not a chart library

Adding recharts / visx / d3 means bundling ~50-150KB for a 60-point
line. SVG `<polyline>` is 6 lines of code, has no transitive deps,
and reads correctly in dark/light mode via `currentColor`. When the
designer wants real charts (multi-series, brushing, hover detail),
they pick a lib then — see the designer hand-off for the suggested
candidates.

## Non-goals

- **No automatic rotation.** The log grows monotonically. A
  follow-up can add a retention env var; for now operators rotate.
- **No per-instrument breakdown.** The composite is logged; the
  three contributing instruments (behavioural, stagnation, KFM)
  are not. A v4.x could log them too.
- **No drift event replay scenario.** Existing
  `scenario drift` exercises one synthetic cycle; we don't need a
  long-form synthetic time series scenario yet.

## Tests

`tests/test_drift_log.py` (4 cases):
- Round-trip a couple of records.
- `limit=N` returns the newest N.
- Empty file returns `[]`.
- Malformed lines are skipped, valid lines preserved.

Full suite: 502 passing.

## Live verification

Each `chimera run` cycle that fires the drift detector (≥3
observations into the session) now writes one row to
`state/drift_log.jsonl`. The dashboard sparkline at
<http://127.0.0.1:3000> renders the trace on next render.
