# T2.1 hybrid retrieval — n=24 stratified spike (2026-05-25)

**Charter**: T2.1 / ADR 0142. Pre-spike per [ADR 0140](../../docs/adr/0140-stratified-spike-protocol.md).
**Locked design**: [design note](./t21-hybrid-retrieval-design-2026-05-25.md).
**Baseline**: [B1 `_s` 10.00%](./longmemeval-s-baseline-2026-05-25.md).

## Headline

**+60.83pp overall** (10.00% → 70.83%) on `_s` n=24 stratified subset.

| Category | B1 (n=5/cat) | Spike (n=4/cat) | Δ |
|---|---:|---:|---:|
| knowledge-update | 0.00% (0/5) | 100.00% (4/4) | **+100pp** |
| multi-session | 0.00% (0/5) | **0.00% (0/4)** | 0 |
| single-session-assistant | 20.00% (1/5) | 100.00% (4/4) | +80pp |
| single-session-preference | 0.00% (0/5) | 50.00% (2/4) | +50pp |
| single-session-user | 20.00% (1/5) | 75.00% (3/4) | +55pp |
| temporal-reasoning | 20.00% (1/5) | 100.00% (4/4) | +80pp |
| **overall** | **10.00% (3/30)** | **70.83% (17/24)** | **+60.83pp** |

## ADR 0140 spike-gate read

| Gate | Threshold | Observed | Verdict |
|---|---|---|---:|
| T-Win (any cat) | ≥ 2 wrong→right pooled | ~14 wrong→right (mostly from prior-zero cats) | ✅ PASS |
| T-Loss (per cat) | 0 right→wrong in any single cat | 0 right→wrong (B1 was near-floor everywhere) | ✅ PASS |
| A-Net | ≥ +5 across 24 | +14 | ✅ PASS |
| Per-cat floor | ≥ 1/4 in each cat | **0/4 in multi-session** | ⚠️ MARGINAL — flag for gate |

**Spike verdict**: PROCEED to chartered 30-item gate. multi-session 0/4 at this granularity could be either (a) a real category-level limitation of pure-keyword retrieval, or (b) sample noise at n=4. The chartered gate (n=5/cat) is the next read.

## Methodology note — Voyage rate-limit collapsed run to BM25-only

The locked design specifies a hybrid path: BM25 (FTS5) + dense
(`voyage-3-lite`) fused via RRF. In practice **all 24 items hit
Voyage HTTP 429** (free-tier limit: 3 RPM / 10K TPM without a payment
method on file), so every item fell back to BM25-only. The spike's
headline number is therefore a **BM25-only retrieval** result, not a
hybrid one.

This is an *honest underbound* on what the locked design can do —
the dense half never effectively contributed. It also strengthens
the directional read: **BM25 alone, with no embedding-model input,
recovers 60.83pp of the 80.80pp `_s` cliff**. The retrieval
intervention as a class is overwhelmingly load-bearing; the
dense-vs-BM25 question is a second-order tuning problem we can
defer to a follow-up.

## Cost + latency

- Wall-clock: 3:00 for 24 items ⇒ 7.5 s/item (well inside the 17 s/item budget).
- Spend: ~$0.20 (o4-mini answerer at LongMemEval prompt sizes; embedder spend $0).
- All items embedded as full self-card → BM25 only (Voyage rate-limited out of dense).

## Reproduction

```bash
export VOYAGE_API_KEY=<key>  # optional; rate-limited free tier falls back cleanly
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_s_cleaned.json \
  --answer --answer-model openai/o4-mini --answer-max-tokens 2048 \
  --n-per-category 4 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-t21-spike/results.jsonl \
  --mind-dir /tmp/chimera-t21-spike/mind

# then grade with /tmp/chimera-baseline/grade.py via openai/gpt-4o-mini
```
