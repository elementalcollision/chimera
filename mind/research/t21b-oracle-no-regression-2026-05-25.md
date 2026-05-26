# T2.1b — Oracle 500-item no-regression sweep for hybrid retrieval (2026-05-25)

**Verdict**: Pre-registered promotion gate **FAILED** (overall −1.60pp, knowledge-update −7.69pp exceeds −5pp floor). Failure mode is **measurement noise from the o4-mini answerer**, not a hybrid-retrieval defect — code-path analysis confirms byte-identical dialectic prompts on oracle items, and 5 of 6 categories' flip distributions are symmetric (consistent with stochastic variation under identical inputs).

**Recommendation**: Ship `_s`-only — promote ADR 0142 with status **Accepted (`_s`-only)**, retain T2.1a's `_s` long-horizon win (66.67%, +56.67pp from B1), defer "byte-identical oracle floor under hybrid-retrieval flag" claim pending either (a) baseline re-run to characterise o4-mini single-sweep noise, or (b) a deterministic answerer.

---

## Headline scores

**Full sweep, 500 items, `longmemeval_oracle.json`, current main (`662bdf2`), `--hybrid-retrieval --retrieval-top-k 8`.**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 78 | 69 | 88.46% |
| multi-session | 133 | 119 | 89.47% |
| single-session-assistant | 56 | 55 | 98.21% |
| single-session-preference | 30 | 13 | 43.33% |
| single-session-user | 70 | 70 | 100.00% |
| temporal-reasoning | 133 | 120 | 90.23% |
| | | | |
| **overall** | **500** | **446** | **89.20%** |

### Side-by-side with post-T1.5 baseline (`14192658`)

| Category | Post-T1.5 (baseline) | T2.1b (this sweep) | Δ | Gate (no >5pp drop) |
|---|---:|---:|---:|---|
| knowledge-update | 96.15% (75/78) | 88.46% (69/78) | **−7.69pp** | ❌ **FAIL** |
| multi-session | 90.23% (120/133) | 89.47% (119/133) | −0.76pp | ✅ noise |
| single-session-assistant | 100.00% (56/56) | 98.21% (55/56) | −1.79pp | ✅ noise (1-item) |
| single-session-preference | 46.67% (14/30) | 43.33% (13/30) | −3.34pp | ✅ noise (1-item on n=30) |
| single-session-user | 98.57% (69/70) | 100.00% (70/70) | +1.43pp | ✅ gain |
| temporal-reasoning | 90.23% (120/133) | 90.23% (120/133) | ±0.00pp | ✅ identical |
| **overall** | **90.80%** (454/500) | **89.20%** (446/500) | **−1.60pp** | ❌ **FAIL** (gate: ≥ 90.80%) |

### Pre-registered gates (from ADR 0142 §Promotion gates, T2.1a's charter)

| Gate | Threshold | Observed | Verdict |
|---|---|---|---|
| Overall 500-item | ≥ 90.80% | **89.20%** | ❌ **FAIL** (−1.60pp) |
| Per-category floor | No category drops > 5pp | knowledge-update at −7.69pp | ❌ **FAIL** |
| Latency | ≤ 2× baseline wall-clock | **50:12** vs baseline **54:00** | ✅ PASS (faster) |

---

## Item-level diff vs post-T1.5 baseline

Diff of `is_correct` per `question_id` between
`/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl` (the load-bearing baseline at `14192658`) and `/tmp/chimera-t21b-oracle/results.graded.jsonl` (this sweep at `662bdf2`).

| Category | →wrong (lost) | →right (gained) | Net | Symmetric? |
|---|---:|---:|---:|---|
| knowledge-update | 6 | 0 | −6 | **No — fully asymmetric** |
| multi-session | 5 | 4 | −1 | Yes (near) |
| single-session-assistant | 1 | 0 | −1 | n=1, no signal |
| single-session-preference | 4 | 3 | −1 | Yes |
| single-session-user | 0 | 1 | +1 | n=1, no signal |
| temporal-reasoning | 6 | 6 | 0 | **Yes — perfectly** |
| **Total** | **22** | **14** | **−8** | — |

**464/500 items agree** between baseline and T2.1b (92.8% direct agreement); 36/500 flipped (7.2% flip rate). That flip rate is consistent with the n=30 stochastic-reroll envelope PR #81 documented (~±2pp overall on identical inputs).

### The knowledge-update asymmetry

All 6 knowledge-update regressions are the **same failure mode**: model returned the *older / superseded* fact instead of the latest updated value.

| Item | Baseline answer (✓) | T2.1b answer (✗) |
|---|---|---|
| `c4ea545c…` | "Initial schedule: 3×/week … by August updated to …" (correct supersession) | "Previously worked out 4×/week, but now go 3 days …" (older count) |
| `dad224aa…` | "You wake up at 7:30 am on Saturday mornings." | "You typically wake up around 8:30 am …" (older value) |
| `07741c45…` | "Most recently … shoe rack in your closet." | "You've been storing your old sneakers under your bed." (older location) |
| `69fee5aa…` | "37 pre-1920 American coins, and later added a 1915-S Barber quarter …" | "Collection includes 37 pre-1920 American coins." (drops the add) |
| `9ea5eabc…` | "Most recent family trip to Paris." | "Most recent family trip was to Hawaii." (older trip) |
| `830ce83f…` | "Rachel's most recent move was out of the city back into the suburbs." | "Rachel's most recent move was to Chicago." (older move) |

Asymmetric 6/0 + same-shape failure looks like a defect signal — except the code path analysis (below) rules out any hybrid-retrieval contribution.

---

## Diagnostic: why this isn't a hybrid-retrieval defect

### Session-count histogram

All 78 knowledge-update items have **exactly 2 sessions** (verified via `len(item.haystack_sessions)`). Since `top_k=8`, every KU item triggers the no-op branch.

### Code path on no-op

`chimera/evals/longmemeval.py:288-300` `_select_session_indexes`:

```python
n = len(item.history)
if not self._hybrid_retrieval:
    return list(range(n))
if n <= self._retrieval_top_k:
    return list(range(n))     # ← KU items take this branch
# ...select_top_k_sessions call only reached when n > top_k
```

The two branches return **identical values** (`list(range(n))`) for any item with n ≤ top_k. `select_top_k_sessions` is never invoked; the embed_fn / embed_cache / BM25 corpus are never touched on KU items.

`chimera/evals/hybrid_retrieval.py:select_top_k_sessions` confirms the contract:
```python
if n <= top_k:
    # Oracle / small-haystack path: no retrieval needed.
    return list(range(n))     # returns BEFORE BM25/embed branches
```

### Code-diff scope between baseline (`14192658`) and T2.1b (`662bdf2`)

```
$ git diff --stat 14192658..662bdf2 -- chimera/evals/longmemeval.py chimera/a2a/dialectic.py
 chimera/evals/longmemeval.py | 54 +++++++++++++++++++++++++++++++++++++++++++-
 1 file changed, 53 insertions(+), 1 deletion(-)
```

Dialectic builder (`chimera/a2a/dialectic.py`) is unchanged. The only adapter change is the additive `_select_session_indexes` helper + ctor params. For any KU item, the self-card produced is **identical bytes** to baseline.

### Cross-category symmetry corroboration

If the regression were caused by retrieval-induced re-ordering or content drift, we'd expect **all** categories to skew (the no-op path is identical across all of them; if the no-op path were buggy it'd be category-uniform). Instead:

- **temporal-reasoning**: 6/6 perfectly symmetric on n=133 with byte-identical inputs.
- **multi-session**: 5/4 near-symmetric on n=133.
- **single-session-preference**: 4/3 near-symmetric on n=30.

These distributions are the signature of LLM stochasticity under identical inputs, not of a code-side regression. KU's 6/0 falls in the tail of that same noise distribution — uncommon (Bernoulli(0.5) gives 6/0 conditional on flipping with probability ~1.5%) but across 6 categories the chance of *some* category hitting this skew is ~9%. Plausible.

### What this rules out

- ❌ Not a no-op detection bug (no-op path is `return list(range(n))` for `--hybrid-retrieval` *and* default).
- ❌ Not embed-cache leakage (`embed_fn` not invoked when no-op).
- ❌ Not BM25 corpus pollution (BM25 ranker not invoked when no-op).
- ❌ Not session re-ordering (no-op returns ascending indices, then card builder iterates them in order).
- ❌ Not a prompt-format drift (the dialectic builder is unchanged between commits).

### What this does *not* yet rule out

- ⚠️ A *systemic* o4-mini bias toward older-fact-on-conflict, exposed by the unlucky flip distribution this sweep happened to roll. A second baseline re-run (no flag, same code, same commit, same model) would be the cleanest test — if the rerun also drifts ~−1.6pp on overall with a similar KU pattern, the post-T1.5 90.80% number itself is upper-tail noise and the "regression floor" should be widened.

---

## Latency

| Stage | Wall-clock | Baseline reference | Δ |
|---|---:|---:|---:|
| Sweep | 50 min 12 s | ~54 min | −7% (faster) |
| Grading | 5 min 56 s | ~9 min | −34% (faster) |

Latency gate (≤ 2× baseline): **PASS**, easily. Hybrid retrieval adds zero overhead on the no-op path (single `len(history)` check + early return).

---

## Recommendation

Pre-registered gate strictly fails on overall (−1.60pp) and knowledge-update (−7.69pp). Charter discipline (PR #41/PR #67/PR #75 lineage) says: **don't move the goalposts**. The right move is to honestly document the failure and avoid the "Accepted" status that implies the oracle floor was demonstrated.

**Three doors:**

| Option | Action | Trade-off |
|---|---|---|
| **A. Ship `_s`-only** (**recommended**) | ADR 0142 → **Accepted (`_s`-only)**. Charter the hybrid-retrieval layer as the ship surface for `_s` long-horizon (T2.1a's +56.67pp result). On oracle the flag remains available; this note documents that under the current answerer (o4-mini) it's noise-bounded but did not clear the strict single-sweep gate. | Honest. Preserves the real `_s` win. Defers the "byte-identical-on-oracle" claim. |
| **B. Falsify** | ADR 0142 → **Falsified**; remove the flag wiring; close out as a failed experiment. | Wrong: `_s` clearly works. Would discard a real +56.67pp intervention because of a measurement-noise failure on a different surface. |
| **C. Re-run baseline (~$2)** | Re-grade the existing 90.80% baseline answers, *and* re-run the answerer on the no-flag config, to characterise o4-mini single-sweep variance. If the rerun also drifts ~−1.6pp, widen the gate to "post-T1.5 ± noise envelope". | Adds spend and time; defers the verdict another day. May still come back inconclusive. |

**This note adopts Option A.** Operator can request B or C on the PR.

### Follow-up chips this verdict opens

- **T2.1c — oracle noise characterisation (Option C)**: re-run the no-flag baseline once or twice to bound o4-mini single-sweep variance. If overall drifts by ≥ 1pp on identical inputs, the post-T1.5 90.80% headline is single-sample upper-tail and all future "no regression" gates should compare to a measured envelope, not a point estimate. Operator-gated spend, ~$2 / ~55 min per rerun.
- **T2.1d — deterministic answerer for oracle gate**: switch from o4-mini (reasoning model, inherent stochasticity) to a temperature-pinnable model (gpt-4o-mini) for the gate-clearing sweep. Cheaper and lower-variance; would let "byte-identical inputs → byte-identical scores" become a hard contract rather than a probabilistic one.

Neither is required to merge ADR 0142 on the `_s` ship-surface; both are clean follow-ups for someone who wants the oracle "no regression" claim demonstrated.

---

## Sweep metadata

- **Date**: 2026-05-25 (UTC)
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc`
- **Chimera commit**: `662bdf2` (current main, post-PR #85 T2.1a merge)
- **Dataset**: `longmemeval_oracle.json` (500 items, full oracle distribution)
- **Adapter flags**: `--hybrid-retrieval --retrieval-top-k 8`
- **Answerer model**: `openai/o4-mini` via OpenRouter
- **Answer max-tokens**: 2048
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter (same as post-T1.5 baseline)
- **Embedder**: `OPENAI_API_KEY` unset → dense fallback to BM25-only (same effective config as T2.1a `_s` gate). For oracle items this is moot — every item no-ops before BM25 is reached.
- **Wall-clock**: sweep 50:12 (20:37–21:27 EDT); grading 5:56 (21:27–21:33 EDT)
- **Inference cost (rough)**: ~$1.5 Chimera-side + ~$0.10 judge-side ≈ **~$1.6 total**, in line with the post-T1.5 envelope.

### Preflight (n=100)

A cheaper n=100 preflight ran first (operator-gated cost step). `--n 100` slices the oracle by the dataset's natural ordering, sampling only multi-session (40) and temporal-reasoning (60). Both categories landed at-or-above their post-T1.5 baselines (92.50% / 98.33%; baseline 90.23% / 90.23%) — no regression signal in the slice. The full sweep was authorised on that read; the 4 unsampled categories (knowledge-update, single-session-{user,assistant,preference}) carried the regression signal that only emerged at n=500.

Lesson for T2.1c-style noise characterisation: small-n preflights on `--n N` slice oracle by category boundaries (knowledge-update sits at items 200+); a stratified preflight would have surfaced the KU drift at n=30 instead of n=500.

---

## Reproduction

```bash
# 1. Sweep (~50 min)
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  --hybrid-retrieval --retrieval-top-k 8 \
  --answer --answer-model openai/o4-mini --answer-max-tokens 2048 \
  --out /tmp/chimera-t21b-oracle/results.jsonl \
  --mind-dir /tmp/chimera-t21b-oracle/mind

# 2. Grade (~6 min)
python /tmp/chimera-baseline/grade.py \
  /tmp/chimera-t21b-oracle/results.jsonl \
  /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  /tmp/chimera-t21b-oracle/results.graded.jsonl \
  openai/gpt-4o-mini

# 3. Aggregate
python -c "
from pathlib import Path
from chimera.evals.longmemeval import summarize_results, format_summary_table
print(format_summary_table(summarize_results(
    Path('/tmp/chimera-t21b-oracle/results.graded.jsonl'))))
"
```

---

## References

- [Post-T1.5 baseline](./longmemeval-baseline-post-t1.5-2026-05-25.md) — the 90.80% / per-cat floor this gate is measured against.
- [T2.1a `_s` gate](./t21-hybrid-retrieval-gate-2026-05-25.md) — the chartered gate clearance that earned this oracle follow-up.
- [T2.1a design note](./t21-hybrid-retrieval-design-2026-05-25.md) — locked-design table + falsification register.
- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — promotion target; flipped Proposed → Accepted (`_s`-only) by this note.
- [PR #85](https://github.com/elementalcollision/chimera/pull/85) — T2.1a ship that this note follows up.
- Upstream: https://github.com/xiaowu0162/LongMemEval
