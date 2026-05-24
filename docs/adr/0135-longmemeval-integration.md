# ADR 0135 — LongMemEval adapter (Phase 4 / item #8)

**Status**: **Proposed** (status locks to Accepted once a baseline sweep validates the adapter end-to-end against the upstream harness)

**Relationship**: Phase 4 item #8 from [ADR 0123](./0123-honcho-inspired-enhancements.md): *"LongMemEval / LoCoMo benchmarks — integrate the eval harness (run their evals; don't port)."* Implements the LongMemEval-first recommendation captured in [`mind/research/eval-harness-2026-05-24.md`](../../mind/research/eval-harness-2026-05-24.md).

## Context

The research note locked two decisions: **(a) integrate LongMemEval first, defer LoCoMo**, and **(b) smallest-viable integration point is a Chimera-side adapter that the upstream harness calls into.** This ADR records the surface that ships in the integration chip.

The upstream LongMemEval harness iterates 500 question/history items across five categories and grades answers with a judge model. Chimera's adapter sits on the answer side: bulk-ingest the history into Chimera's memory surfaces, then answer the question via the dialectic API (ADR 0133). Grading remains the upstream harness's job.

## Locked design

### Module: `chimera/evals/longmemeval.py`

Public surface:

- **`LongMemEvalItem`** dataclass — typed schema mirroring upstream JSON. Accepts both canonical (`item_id`, `history`, `expected_answer`) and upstream-aliased (`id`, `haystack_sessions`, `answer`) keys via `from_dict`. Unknown extras land in `.extra`.
- **`AnswerResult`** dataclass — `(item_id, question, answer, sources_used, category, expected_answer, error)`. JSON-serialisable via `to_dict()`. `error` is populated instead of raising so one bad item can't kill a sweep.
- **`LongMemEvalAdapter`** class:
  - `ingest_history(item)` — writes one markdown file per session under `mind/wiki/longmemeval/`. FTS5 picks them up automatically (ADR 0080).
  - `answer(item)` — gathers dialectic context (ADR 0133) and returns the assembled prompt as the `answer`. The upstream grader pipes this through whichever judge model the operator pays for.
  - `reset()` — truncates the scratch ingest dir between items. Idempotent.
- **`load_items(path)`** / **`write_results(results, path)`** — JSONL I/O. Malformed lines skipped silently (crash-mid-write tolerance, matching the rest of `mind/`).
- **`run_batch(adapter, items, *, limit, subset)`** — iterates items through the adapter, resets between items, returns the result list. `subset` is a case-insensitive substring filter on `.category`; `limit` caps after filter.

### CLI verb: `chimera evals longmemeval`

Attaches under a new `evals` parent verb (sibling of `peers`, `trust`, `escalations`). Flags:

- `--items PATH` — JSONL items file (the upstream-distributed dataset, or a custom subset).
- `--smoke` — runs a built-in 3-item synthetic fixture covering `single-session-user`, `multi-session`, and `abstention`. **The smoke path is the load-bearing test surface** until an operator has the real dataset locally — it verifies the adapter end-to-end without depending on the upstream download.
- `--n N` — cap items processed (after subset filter).
- `--subset CAT` — filter by category.
- `--out PATH` — output JSONL location. Defaults to `mind/evals/longmemeval-<UTC-timestamp>.jsonl`.
- `--mind-dir PATH` — env override for this call.

`--items` and `--smoke` are mutually-exclusive-via-validation (one of them is required; passing neither prints an error and exits 2).

### Result substrate: `mind/evals/longmemeval-<ts>.jsonl`

One JSON object per result. Operator-grep-able. Sibling of `mind/peer_beliefs.jsonl` (ADR 0132) and `mind/reflection_conclusions.jsonl` (ADR 0124). The substrate name (`mind/evals/`) is reserved for future adapters.

## Why the adapter returns a prompt, not an LLM answer

Same rationale as the `chimera-ask` MCP tool (ADR 0133 §"Why the MCP tool returns the prompt, not the answer"):

- **Cost containment.** If the adapter ran the LLM for every item, a full LongMemEval sweep (500 items) would run 500 sonnet-tier calls against our caps. Returning the dialectic-assembled prompt makes the upstream grader pay for the judging.
- **Judge choice belongs to the operator.** Different judge models produce different scores; the operator picks the one that matches their cost / variance budget.
- **Reproducibility.** The prompt is deterministic from the ingested history; the judge's answer is not. Capturing the prompt makes failures debuggable.

## Out of scope (this PR — explicit)

- **Upstream dataset bundling.** The operator clones LongMemEval and points `--items` at it. No PyPI extra commitment; no auto-download.
- **Judge model invocation.** The upstream harness has its own grader; we produce answers for it to grade.
- **Result aggregation / category scoring tables.** The JSONL is the source of truth; aggregation lands in a follow-up alongside the first baseline sweep.
- **Dashboard widget.** Result surfacing follows the baseline sweep.
- **LoCoMo adapter.** Deferred per research-note recommendation.
- **Auto-cadence runs.** Operator-invoked only.
- **Comparison-vs-baseline regression check.** Needs at least two sweeps to compare; lands after the second.
- **Bulk-ingest enhancements.** Today's ingest writes session markdown to `mind/wiki/longmemeval/`. The research note flagged "re-run the Reflection engine over the history for deriver-style conclusions" as the next sophistication; that's a follow-up, not this chip.

## Consequences

### Positive

- Phase 4 #8 lands as a tight, charter-disciplined chip — same shape as the successful Phase 1–3 chips. The lesson from PR #41 is applied: surface is locked; implementation is minimal.
- The `mind/evals/` substrate is reserved for future adapters (LoCoMo when it lands, custom internal benchmarks) without re-shaping the namespace.
- The smoke fixture means CI can verify the adapter end-to-end with zero external deps.
- Future Phase 4 #6 retries can use the baseline LongMemEval numbers as a regression gate — *"hybrid search must not regress category X by more than Y%"* becomes a falsifiable claim.

### Negative

- The adapter's value depends on running a real sweep with the upstream dataset. Until that happens, the value is just "the surface exists" — no measurement yet.
- One more CLI parent verb (`evals`). Mitigated by the operator-facing namespace already being shallow.
- Bulk ingestion writes to `mind/wiki/longmemeval/`, which means a full-sweep run pollutes the wiki FTS index with synthetic content until the next `reset`. The adapter's final-reset behaviour mitigates this between items, but a sweep that crashes mid-flight leaves leftover files. Operator cleans up by `rm -rf mind/wiki/longmemeval/`.

## Status promotion criteria

ADR status moves from **Proposed** to **Accepted** when all three hold:

1. One full or partial sweep has been run with the upstream dataset.
2. The output JSONL has been graded by the upstream judge and category scores recorded.
3. The baseline scores are filed at `mind/research/longmemeval-baseline-<date>.md` so future PRs can reference a concrete number when claiming improvements.

Until then, the surface is locked but the *recommendation* (LongMemEval-first integration) stays provisional.

## References

- [`mind/research/eval-harness-2026-05-24.md`](../../mind/research/eval-harness-2026-05-24.md) — research note that locked LongMemEval-first.
- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 4 anchor.
- [ADR 0080 — mind/wiki FTS5 search](./0080-wiki-fts-search.md) — retrieval substrate used by the adapter.
- [ADR 0124 — Deriver-style structured-output extraction](./0124-deriver-style-extraction.md) — provider-agnostic module pattern reused here.
- [ADR 0133 — Dialectic API](./0133-dialectic-api.md) — the Q&A surface the adapter wraps.
- LongMemEval — Wu, Y. et al. ICLR 2024. https://github.com/xiaowu0162/LongMemEval
- [`chimera/evals/longmemeval.py`](../../chimera/evals/longmemeval.py), [`chimera/cli.py`](../../chimera/cli.py).
