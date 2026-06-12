# ADR 0181 — Evals accuracy gate (`chimera evals summarize`)

**Status:** Accepted (2026-06-12)

## Context

The consolidation roadmap's open item is "evals (LongMemEval/LoCoMo) as a
**gated** nightly, not just unit tests in the main suite." Surveying the
existing harness showed most of it is already built:

- the adapters (`chimera evals longmemeval` / `locomo`) produce answers +
  provenance, with `--answer` running them through OpenRouter (key-gated);
- `summarize_results()` aggregates a graded JSONL into per-category
  accuracy; `format_summary_table()` renders it;
- 95 adapter unit tests already run in the default CI suite, so adapter
  *regressions* are caught today.

Two things were missing for a *gate*:

1. **No CLI surface wired `summarize_results` to an exit code.** It was a
   library function nothing called — there was no "fail the build if
   accuracy drops" path.
2. **The live nightly is decision-gated** (grader choice, CI secrets,
   dataset hosting, budget/threshold) — and per [ADR 0135](./0135-longmemeval-adapter.md)
   the project *deliberately does not own grading* ("grading is the
   harness's job; we let the operator pipe results to whichever grader
   they're paying for"). So building a Chimera-native judge would cut
   against an existing decision.

The decision-free, in-grain slice is therefore the **gate itself**:
grader-agnostic, key-free, and the one piece every nightly needs
regardless of which grader or budget the operator picks.

## Decision

### `chimera evals summarize` — the accuracy gate

A new evals subcommand that consumes a **graded** JSONL (each row carries
a boolean correctness field — `is_correct` by default — written by
whatever upstream grader the operator ran, per ADR 0135), reuses the
existing `summarize_results` / `format_summary_table`, prints per-category
accuracy, and returns a **nonzero exit code** on:

- `--min-accuracy X` — overall accuracy below an absolute floor; and/or
- `--baseline prior.json --tolerance T` — overall accuracy regressed more
  than `T` below a stored prior `--json` summary.

`--json` emits the summary for storage as the next run's baseline. The
verb makes no provider calls and needs no keys or datasets, so it is fully
unit-tested (`tests/test_evals_summarize.py`, 9 cases: threshold
pass/fail, baseline regression/improvement, custom field, JSON round-trip
as next baseline, and the error exit codes).

### Nightly workflow template

`.github/workflows/evals-nightly.yml` ships as a **manual-dispatch
template** (no schedule yet, so it doesn't run noisily before the live
decisions are made):

- a **plumbing** job that runs today, keyless — the adapter `--smoke` runs
  plus the gate self-test against a committed synthetic fixture
  (`tests/fixtures/graded_smoke.jsonl`) — proving the adapter→gate pipe on
  the runner;
- a fully-spelled-out, commented **live** job annotating exactly which
  step each of the four go-live decisions unblocks.

## Decisions required to go live (operator)

> **Operator decision (2026-06-12): HOLD go-live.** Secrets "not yet",
> grader "decide later". The keyless plumbing job stays the active
> surface; the four decisions below remain open. The downstream
> embedding-routing item's backend was, however, resolved the same day:
> **Ollama (local, bge-m3)** for ADR 0134 §6.b.

The template can't be scheduled until these are made — they are not
technical blockers but choices with cost/policy implications:

1. **Grader** — which upstream grader writes `is_correct`? LongMemEval's
   `src/evaluation/evaluate_qa.py` (an LLM judge), a local judge, or
   deterministic match. (ADR 0135 keeps this the operator's call.)
2. **Secrets** — add `OPENROUTER_API_KEY` (answers + judge) and optionally
   `VOYAGE_API_KEY` (dense retrieval) as repo secrets. Schedule-triggered
   on main only, so fork-PR exposure is not a concern — but it is real
   spend keyed to the account.
3. **Dataset hosting** — LongMemEval (~500 items, tens of MB) and LoCoMo
   (`locomo10.json`) are external; fetch+`actions/cache` at run time, or
   stage as private release assets. Do not vendor.
4. **Budget + cadence + threshold** — subset size per run (e.g.
   `--n-per-category 5`), schedule, and the gate's `--min-accuracy` floor
   / baseline tolerance. Recommendation: **report-only for ~2 weeks** to
   learn run-to-run variance before turning the threshold into a hard
   gate (LLM-judged accuracy is noisy; a day-one absolute threshold will
   flake).

## Consequences

- The "gate" half of "gated nightly" is **done and CI-tested today**;
  going live is now purely the four decisions above plus the dataset-fetch
  + grade glue scripts they imply.
- This also unblocks the roadmap's *next* item — embedding-based routing
  (ADRs 0165/0166), explicitly gated on "eval gating in place" — though
  that additionally needs the ADR 0134 §6.b embedding-backend decision
  (Voyage vs Ollama) before it can start.

## Falsification / revisit triggers

- If the operator's grader emits a non-boolean score (e.g. a 0–1
  graded-relevance float), extend the gate with a `--score-field` +
  `--score-threshold` mode rather than forcing a boolean projection.
- If nightly variance makes the baseline-regression gate flap, switch the
  baseline from "last run" to a rolling median over N runs.
