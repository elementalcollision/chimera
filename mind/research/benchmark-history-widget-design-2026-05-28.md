# Benchmark-history widget — design note

**Date**: 2026-05-28
**Status**: Shipped (chip/benchmark-history-widget)
**Chip lineage**: Net-new dashboard widget. Originally part of "Operation
4" (v4.115.0 release-operationalization batch) before the v35 cascade
pulled focus. Picked up now that v4.116.0 has shipped and the cascade is
closed.

## Why

User framing from 2026-05-25: *"Chimera hasn't provided any outputs
recently. All we've been doing is testing."* The control-plane dashboard
is the operator-facing surface; surfacing the benchmark headline numbers
we have accumulated (LongMemEval oracle + `_s`, LoCoMo full + envelope +
hybrid) makes those outputs visible to the operator without depending
on Chimera-the-agent converging on anything.

## Decision: Option B — curated `mind/benchmarks.json`

Two approaches were considered. **Option B (curated JSON file)** was
picked over **Option A (parse research notes)**.

### Option A — Parse `mind/research/*-baseline-*.md`

Walks `mind/research/` looking for files matching patterns like
`longmemeval-baseline-*.md`, `locomo-*.md`, `t21*.md`. Extracts headline
accuracy + date from the first table in each.

- **Pro**: Source of truth stays in the research notes; no separate
  file to maintain.
- **Con**: Note formats are heterogeneous. Different authors use
  different table layouts, headline columns appear in different orders,
  some notes lead with a per-category breakdown and headline appears
  later, some use "accuracy" vs "headline" vs "F1" terminology. A
  robust parser is significantly more code than a small JSON loader,
  and it would silently miss notes whose filename pattern was not
  anticipated.

### Option B — `mind/benchmarks.json` (chosen)

A small JSON file at `mind/benchmarks.json` containing curated entries
with structured fields (id, benchmark, config, n, headline_pct, optional
envelope, date, source_note, optional notes).

- **Pro**: Type-safe via TypeScript on the loader side; entries are
  explicit (no "did the parser pick this up?" question); fast to load;
  easy to add new rows in a PR review.
- **Pro**: Becomes a small piece of operator-facing infrastructure that
  future chips can append to as new benchmarks land.
- **Con**: One more file to keep in sync — adding a benchmark now
  requires both the research note (canonical narrative) and a JSON
  entry (dashboard surface).

The con is mitigated by the README workflow: research note lands first,
JSON entry is appended in the same PR or a small follow-up.

## Where the source-of-truth lives

- `mind/benchmarks.json` — **single source of truth for the dashboard**.
- `mind/research/*.md` — **canonical narrative** for *why* a number is
  what it is (methodology, gates, per-category breakdowns, decision
  rules, envelope reasoning).
- The widget links each row to its `source_note` so an operator who
  wants context is one click away.

The widget intentionally does **not** duplicate per-category breakdowns
or envelope tables in the dashboard. Those belong in the research note.
v1 shows headline + benchmark + config + n + envelope summary + date +
link.

## Schema

Documented inline at the top of `mind/benchmarks.json` via a
`$schema_comment` field, and in `control-plane/README.md` under the
"Benchmark history" section. Fields:

| field | required | type | notes |
|---|---|---|---|
| id | yes | string | kebab-case, stable, used as React key |
| benchmark | yes | string | display name |
| config | yes | string | model + retrieval summary |
| n | yes | number | sample size |
| headline_pct | yes | number | 0–100 |
| envelope.mean_pct | no | number | center of noise envelope |
| envelope.sigma_pp | no | number | percentage-point sigma |
| envelope.gate_pct | no | number | min accuracy gate (mean − 2σ) |
| date | yes | string | ISO YYYY-MM-DD |
| source_note | yes | string | repo-relative path to research note |
| notes | no | string | one-line context, shown in row tooltip |

## Fail-soft posture

If `mind/benchmarks.json` is missing or malformed, the widget renders a
placeholder with a pointer to the README. Never crashes the page. This
matches the existing dashboard convention (HotSignaturesWidget renders
a "no hot signatures" empty state; this widget renders a "no benchmarks
recorded yet" placeholder).

## Seed entries (v4.114–v4.116)

Seven rows pre-populated from research notes already in `mind/research/`:

1. `lme-oracle-post-t1.5` — LongMemEval oracle, o4-mini, n=500, 90.80%
2. `lme-s-baseline` — LongMemEval `_s`, o4-mini, n=30, 10.00%
3. `lme-s-hybrid` — LongMemEval `_s` + hybrid, o4-mini top_k=8, 66.67%
4. `lme-oracle-noise` — LongMemEval oracle envelope, mean 90.13% ± 0.83pp
5. `locomo-f1` — LoCoMo full, gpt-4o-mini, n=1986, 49.35%
6. `locomo-f3-envelope` — LoCoMo envelope, mean 48.86% ± 0.46pp
7. `locomo-f2-hybrid` — LoCoMo + hybrid, gpt-4o-mini top_k=8, 59.37%

## Scope discipline

Locked at ≤6 files. Final file count: 6 (`mind/benchmarks.json`,
`control-plane/lib/benchmarks.ts`, the widget, the page.tsx wire-up,
the README addition, this design note). No Python touched, no ADR
modified, no soak script touched, no existing dashboard widget touched.

## Deferred (NOT in v1)

- Envelope-comparison view ("did the new run regress past the gate?")
- Per-category drill-down (currently lives only in research notes)
- Time-series chart (e.g., LoCoMo headline over successive runs)
- Sort/filter UI
- Auto-extraction from research notes (Option A)

All future v2 affordances. Future chips append.
