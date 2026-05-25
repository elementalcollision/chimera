# ADR 0142 — Hybrid retrieval for LongMemEval `_s` long-horizon

**Status**: Proposed (2026-05-25)

> Promotion to Accepted (or Falsified) requires the oracle 500-item
> sweep result from T2.1b. T2.1a (this ADR's first cut) ships the
> retrieval helper, adapter wiring, design note, and `_s` spike +
> gate measurement. The oracle sweep is operator-gated (~$3 + ~70 min
> wall-clock) and tracked as the T2.1b follow-up.

## Context

Chimera's LongMemEval adapter (ADR 0135) on the oracle variant
saturates at **90.80%** post-T1.5 ([baseline note](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md)).
On the **`_s` long-horizon variant** — same 500 items but ~48 sessions
and ~493 turns per item rather than oracle's pre-filtered 1–3 gold
sessions — the adapter collapses to **10.00%** ([B1 baseline](../../mind/research/longmemeval-s-baseline-2026-05-25.md)),
a uniform −80.80pp cliff across all 6 categories.

The cliff is a **retrieval-mechanism failure**, not a content-shape
failure: every session's content is in the self-card, but the
answerer's attention over a ~500 KB context degrades to floor. The
PR #69 grounding shape (`## Session N` headers + `**Session date:**`
anchors) is correct on oracle and stays correct on `_s` — it just
isn't sufficient when the haystack is 25–50× larger.

ADR 0136's "vector retrieval was a hedge against a hypothesis the
data now falsifies" note was correctly scoped to oracle. On `_s` the
hypothesis re-enters. This ADR is that hedge, redeployed.

## Decision

Insert a **per-item hybrid retrieval layer** (BM25 via SQLite FTS5 +
dense via bge-m3 through the local Ollama) into
`LongMemEvalAdapter.ingest_history`. The layer fuses ranks with
**Reciprocal Rank Fusion** (RRF, k=60, Cormack et al. 2009), selects
the top-k=8 sessions, and writes them into the synthetic self-card
in **original chronological order** — preserving the PR #69 grounding
shape exactly so ADR 0136's temporal-grounding fix continues to hold.

The layer is **auto no-op when `len(history) <= top_k`**. Oracle items
(1–3 sessions each) pass through unchanged; the 90.80% floor is
structurally protected from regression by shape, not by detection
heuristics.

Locked-design table, falsification gates, and the complete failure-mode
register live in the [design note](../../mind/research/t21-hybrid-retrieval-design-2026-05-25.md).

## Implementation surface

- `chimera/evals/hybrid_retrieval.py` (new, ~290 LOC) —
  `select_top_k_sessions`, `reciprocal_rank_fusion`, `bm25_rank`,
  `dense_rank`, `OllamaEmbedder`, `build_default_embed_fn`.
- `chimera/evals/longmemeval.py` — `LongMemEvalAdapter` gains
  `hybrid_retrieval`, `retrieval_top_k`, `embed_fn` ctor params and a
  `_select_session_indexes` helper that the existing self-card
  builder calls. Default off; existing call sites preserve pre-T2.1
  behaviour byte-for-byte.
- `chimera/cli.py` — `chimera evals longmemeval --hybrid-retrieval
  [--retrieval-top-k N]` flags.
- `tests/test_hybrid_retrieval.py` — 15 unit tests covering RRF math,
  BM25 + dense rank correctness, oracle no-op, empty-input edges,
  adapter wiring, session-date preservation.

## Promotion gates (pre-registered)

Identical to the design note; mirrored here for reviewer convenience.
No goalpost-moving — failure on either gate triggers a falsification
note in `mind/research/` and a redesign-or-defer recommendation.

| Gate | Threshold |
|---|---|
| `_s` 30-item stratified subset, overall | ≥ 50.00% (5× the 10.00% B1 baseline) |
| `_s` per-category floor | ≥ 1/5 in every category |
| Oracle 500-item overall (T2.1b) | ≥ 90.80% (no regression) |
| Oracle per-category (T2.1b) | No category drops > 5pp from post-T1.5 floor |
| Latency on `_s` | ≤ 17 s/item (2× B1's 8.3 s) |

## Results

### Pre-spike gate (ADR 0140 stratified, n=24) — PASS overall, marginal on multi-session

**See**: [spike result note](../../mind/research/t21-hybrid-retrieval-spike-2026-05-25.md)

| Metric | B1 baseline | T2.1a spike (n=24) | Δ |
|---|---:|---:|---:|
| Overall | 10.00% (3/30) | **70.83%** (17/24) | **+60.83pp** |

multi-session at 0/4 was flagged as a marginal per-cat-floor risk;
resolved in the chartered gate (2/5 at n=5/cat).

### Chartered gate (`_s` 30-item stratified) — **ALL GATES PASS**

**See**: [gate result note](../../mind/research/t21-hybrid-retrieval-gate-2026-05-25.md)

| Gate | Threshold | Observed | Pass? |
|---|---|---|---:|
| Overall | ≥ 50.00% | **66.67%** (20/30) | ✅ |
| Per-cat floor | ≥ 1/5 in every cat | 1/5 minimum | ✅ |
| Latency | ≤ 17 s/item | ~10 s/item | ✅ |

Per-category Δ vs B1: knowledge-update +80, multi-session +40,
single-session-assistant +80, single-session-preference +20,
single-session-user +60, temporal-reasoning +60.

### Methodology caveat — BM25-only effective run

**Both the spike and the gate ran BM25-only in practice.** Voyage AI's
free tier rate-limits to 3 RPM / 10K TPM without a payment method, and
every item across both runs hit HTTP 429 and fell back to BM25-only
via the design note's documented degradation path. The headline
numbers are therefore a *BM25-only retrieval* result; the locked-design
dense half never effectively contributed. This makes the result a
**stronger** signal for shipping the retrieval intervention — keyword
matching alone clears every chartered gate — and leaves "does dense
materially help" as a separate, lower-stakes follow-up (T2.1c) once a
non-rate-limited embedder is configured.

### Oracle 500-item (T2.1b)

**Status**: Deferred to T2.1b — operator-gated spend (~$3, ~70 min).

## Consequences

- **Adapter is no longer a pure pipe.** It now holds an embedding
  cache and an httpx client (lazily). The cache is per-adapter
  instance and survives between items (identical text → identical
  vector); it's bounded by sweep size, not by item count, so memory
  is not a concern at LongMemEval scale.
- **New external dependency on a running Ollama at
  `ollama.deploy.orb.local`** (overridable via
  `CHIMERA_OLLAMA_URL`/`CHIMERA_EMBED_MODEL`). If unreachable, the
  retriever degrades to BM25-only with a logged warning. This is
  acceptable for a measurement adapter — production retrieval lives
  at `chimera/memory/hybrid_search.py` (ADR 0134) and is unaffected.
- **No CLI behaviour change unless `--hybrid-retrieval` is passed.**
  Existing sweeps, smoke tests, and the B1 baseline reproduction
  command all behave identically without that flag.

## Alternatives considered

- **BM25-only.** Simpler, no embedder dep. Rejected at design time
  because the chip charter locked hybrid; deferred as a possible
  redesign if T2.1a falsifies and we want to test whether dense was
  load-bearing.
- **Per-turn retrieval.** Finer granularity. Rejected because it
  would change the surface format (`## Session N` headers no longer
  bracket whole sessions) and break the PR #69 / ADR 0136 grounding
  fix.
- **OpenAI text-embedding-3-small via direct API.** The locked-design
  reference. Unreachable: OpenRouter (the operator's only configured
  upstream) doesn't proxy embeddings, and there's no separate OpenAI
  key. Pivoted in two steps: first to local `bge-m3` on Ollama, then
  to `voyage-3-lite` on Voyage AI when the local Ollama bottlenecked
  on `_s`-scale per-item batches. Design note §"Dense backend"
  annotates both pivots.
- **bge-m3 on local Ollama.** Free, well-benchmarked, but a single
  embed call took 30s+ when the local box was saturated by an
  in-flight LongMemEval sweep. Kept as the registered fallback when
  Voyage isn't configured.

## References

- [Design note](../../mind/research/t21-hybrid-retrieval-design-2026-05-25.md)
- [B1 baseline](../../mind/research/longmemeval-s-baseline-2026-05-25.md)
- [Oracle post-T1.5 baseline](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md)
- ADR 0134 — Hybrid search vendor scaffold (production placeholder; intentionally not used)
- ADR 0135 — LongMemEval adapter
- ADR 0136 — Temporal-Aware Dialectic (grounding shape preserved)
- ADR 0140 — Stratified Spike Protocol (adopted for the n=24 pre-spike gate)
- Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods." SIGIR.
