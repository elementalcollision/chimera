# T2.1 — Hybrid retrieval for LongMemEval `_s` long-horizon (locked design, 2026-05-25)

**Status**: Locked-design, pre-code. This note is the spec for the
implementation in [`chimera/evals/hybrid_retrieval.py`](../../chimera/evals/hybrid_retrieval.py)
and the adapter-wiring change in [`chimera/evals/longmemeval.py`](../../chimera/evals/longmemeval.py).
Charter: T2.1, motivated by [`longmemeval-s-baseline-2026-05-25.md`](./longmemeval-s-baseline-2026-05-25.md)
(the −80.80pp cliff at `_s` vs oracle).

The deliverable is split per the chip's discipline rule (≤8 files /
≤2hr per PR):

- **T2.1a (this PR)** — design + retrieval helper + tests + adapter
  wiring + `_s` spike + `_s` gate + ADR 0142 Proposed. No oracle
  sweep — explicitly operator-gated.
- **T2.1b (follow-up)** — oracle 500-item sweep + ADR 0142 promotion
  decision (Accepted or Falsified). Operator-authorized spend.

## Problem (one paragraph)

Chip B1 ([baseline](./longmemeval-s-baseline-2026-05-25.md)) measured
**10.00% on `_s`** against **90.80% on oracle** — a uniform −80.80pp
collapse across all six categories. The current adapter writes every
session into the synthetic self-card; on `_s` that's 40–60 sessions
and ~500 KB per call, and the answerer's attention over the right
sessions degrades to floor. The intervention is to insert a per-item
retrieval layer between ingest and the answerer that ships only the
top-k matched sessions, preserving the PR #69 grounding shape.

## Locked-design table

| Variable | Choice | Why |
|---|---|---|
| **Retrieval mechanism** | Hybrid (BM25 + dense) | Chip charter locks this; BM25 alone misses paraphrase, dense alone misses rare proper nouns / numbers |
| **BM25 backend** | SQLite FTS5 (in-memory `:memory:` connection, per-item) | Already shipped (`chimera/memory/wiki_search.py` uses FTS5); no new deps; per-item index build is fast (~ms for 50 sessions) |
| **Dense backend** | `voyage-3-lite` (cloud, OpenAI-shaped `/v1/embeddings`) via `VOYAGE_API_KEY`. Local `bge-m3:latest` (1024-d via Ollama at `http://ollama.deploy.orb.local/api/embed`) is the registered fallback when Voyage isn't configured. | "Comparable" to the chip's stated `text-embedding-3-small` (OpenRouter doesn't proxy embeddings; the operator's stack has no separate OpenAI key). Voyage-3-lite is well-benchmarked on retrieval and cloud-hosted so per-item latency stays ~1–2 s even on `_s`-scale batches. **The local Ollama path was tried first and bottlenecked on `_s` items (a single embed call took 30s+ when the host was under load), so cloud Voyage is the primary path for measurement.** |
| **Embedding fallback** | If no embed backend is reachable → BM25-only with a logged warning | Honest degradation; lets tests run without the network; the spike-gate measurement still requires the embedder live (we verify with a 1-char liveness probe before each run) |
| **Fusion** | Reciprocal Rank Fusion (RRF) with k=60 | Scale-free across BM25 raw scores vs cosine; standard hyperparam (Cormack et al. 2009 + recent retrieval lit); no per-corpus tuning; weighted-score blends require calibrating two heterogenous score ranges and we don't have a held-out set for that |
| **top-k** | 8 sessions | Median oracle item has 1–3 gold sessions, so 8 gives ~3× headroom for retrieval noise; ~8/48 = ~17% of an `_s` haystack ⇒ ~15× compression vs current adapter |
| **Ranking unit** | Whole session (concat of all turns in that session, plus session date if present) | Session is the existing self-card unit; finer-grained retrieval (per-turn) would change the surface format which charter forbids |
| **Surface format** | Unchanged from PR #69: `## Session N` headers + `**Session date:**` anchors, chronological order by original session index | Charter requirement; preserves the temporal-grounding fix |
| **Oracle no-op detection** | `len(item.history) <= top_k` → ship all sessions in original order, zero retrieval cost | Parameter-free and shape-driven; oracle items (1–3 sessions) auto-pass through unchanged ⇒ no regression risk for the 90.80% floor |
| **Empty-sessions / pathological** | If `len(item.history) == 0`, write the header-only card unchanged. If `len(query) == 0`, emit all sessions unchanged (degrades to no-op) | Match existing adapter behavior |
| **Per-adapter embedding cache** | Dict keyed by `sha256(content)` → vector, scoped to adapter instance | Cheap insurance against duplicate sessions across items; bounded by sweep size; cleared on `reset()` is **not** done — cache survives between items, since identical text → identical vector |
| **Determinism** | RRF is deterministic given fixed inputs; OpenAI embeddings are deterministic for `text-embedding-3-small` (same input → same vector); BM25 over a fixed corpus is deterministic | Reproducible spike-gate results across re-runs |
| **Latency budget** | ≤17 s/item on `_s` (2× current 8.3 s baseline) | One embedding call per item (batched: 1 query + N sessions in a single API call) ⇒ ~1–2 s added; FTS5 index build ~ms; total well under budget |

## Pre-registered promotion gates (locked, do not move)

These mirror the chip charter verbatim. Failure on either gate ⇒
falsification note + redesign or Option-C-style defer; no
goalpost-moving.

| Gate | Threshold | Measurement |
|---|---|---|
| **`_s` 30-item stratified subset, overall** | ≥ 50.00% (5× the 10.00% B1 baseline) | `chimera evals longmemeval --items longmemeval_s_cleaned.json --answer --n-per-category 5 --hybrid-retrieval` |
| **`_s` per-category floor** | ≥ 1/5 in every category (no category at 0) | Same run |
| **Oracle 500-item overall** | ≥ 90.80% (no regression) | `chimera evals longmemeval --items longmemeval_oracle.json --answer --hybrid-retrieval` (**deferred to T2.1b — operator-gated**) |
| **Oracle per-category** | No category drops > 5pp from post-T1.5 floor | Same run |
| **Latency** | ≤ 17 s/item on `_s` | Wall-clock from spike run |

## Pre-spike per-ADR-0140 stratified gate (n=24 spike)

Per [ADR 0140](../../docs/adr/0140-stratified-spike-protocol.md),
adopting chips embed a locked-design gate table. T2.1's retrieval
surface touches every category's grounding (all 6 LongMemEval types
route through the self-card), so the stratified protocol applies.
The chip charter additionally locks an `_s`-specific 30-item gate
above; the n=24 spike below is the **cheap pre-spike** that fires
before the 30-item gate is run, to catch obvious regressions for
~$0.30.

| Variable | Choice |
|---|---|
| **Sampling** | First 4 items per category from `longmemeval_s_cleaned.json` (n=24); stratified across all 6 categories |
| **Pre-baseline** | The B1 `_s` 30-item baseline ([`longmemeval-s-baseline-2026-05-25.md`](./longmemeval-s-baseline-2026-05-25.md)); per-category accuracy is the comparison anchor |
| **Target category** | All 6 (T2.1's intervention is retrieval, which is mechanism-level, not category-localized) |
| **T-Win (any cat)** | ≥ 2 wrong→right in the target run vs baseline pooled across categories |
| **T-Loss (any cat)** | 0 right→wrong in any single category (per-cat O-Loss tolerance = 0; with the baseline at ~10%, almost no items were right to begin with, so right→wrong should be rare-to-impossible) |
| **A-Net** | ≥ +5 across all 24 items (intervention should show a clear positive direction) |
| **PASS authorizes** | The 30-item `_s` chartered gate above |
| **FAIL action** | Abort. Falsify in `mind/research/t21-hybrid-retrieval-spike-2026-05-25.md`. Do **not** run the chartered 30-item gate; do not spend oracle-sweep budget |

## Out of scope (T2.1a)

- Caching the retrieval index across items.
- Cross-item embedding sharing or batch-embedding all sessions
  upfront (each item's index is per-item, by charter).
- Surfacing retrieval provenance into `AnswerResult.sources_used`
  beyond the existing semantics (sessions chosen are visible via the
  scratch self-card on disk).
- A CLI flag for tuning top-k / k_rrf — both locked above.
- Per-turn retrieval (would change surface format).
- Productionizing this retriever for non-LongMemEval surfaces —
  this is a measurement adapter, not the canonical Chimera retriever.
  The shipped scaffold at `chimera/memory/hybrid_search.py` (ADR 0134)
  remains the production placeholder.

## Out of scope (T2.1b)

- Anything besides the oracle 500-item sweep + ADR promotion
  decision + result note. If the oracle gate fails, T2.1b's
  deliverable is a falsification note; no rescue-engineering.

## Failure-mode register (what could go wrong, pre-registered)

| Failure | Detection | Action |
|---|---|---|
| Spike `_s` shows < +5 net | Spike result table | Falsify, do not run gate |
| Spike passes, gate `_s` shows < 50% | Gate result table | Falsify, do not run oracle |
| Gate `_s` passes (≥50%), oracle regresses > 5pp in any cat | Oracle result table (T2.1b) | Falsify oracle gate, document the trade-off; recommend either accepting the regression as a trade for `_s` recovery, or redesigning (e.g. `_s`-only path) |
| Local Ollama unreachable at sweep time | Run logs (warning emitted by `build_default_embed_fn`) | Restart Ollama and re-run; do NOT report BM25-only numbers as the gate result — that would conflate two interventions |
| Answerer/judge: operator-directed pivot from B1's `openai/o4-mini` to `inclusionai/ring-2.6-1t` (fallback `deepseek/deepseek-v4-pro`) | Spike header / gate header notes this is NOT apples-to-apples vs B1's 10.00% | Report deltas honestly; if the new answerer alone changes B1's number materially, note it in the spike result before claiming retrieval credit |
| Latency > 17 s/item | Run logs | Profile, identify bottleneck (likely a per-session embedding call rather than a single batched call), patch, re-measure |

## References

- B1 baseline: [`longmemeval-s-baseline-2026-05-25.md`](./longmemeval-s-baseline-2026-05-25.md)
- Oracle baseline: [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md)
- ADR 0134 — Hybrid search vendor scaffold (production placeholder; intentionally not used here)
- ADR 0136 — Temporal-Aware Dialectic (grounding shape preserved)
- ADR 0140 — Stratified Spike Protocol (spike gate above adopts this)
- Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods." SIGIR.
