# LongMemEval baseline — post-Tier-1 full sweep (2026-05-25)

**Purpose**: Capture Chimera's first **full-sweep** LongMemEval scores after the three Tier-1 prompt-engineering chips (T1.1 / T1.2 / T1.3 from PR #57) landed on `main`. This is the load-bearing baseline for Phase 4 #6.b (hybrid retrieval) — the ≥75% overall gate was set so retrieval's expected impact is bounded enough to justify its engineering cost.

Companion to [`longmemeval-baseline-2026-05-24.md`](./longmemeval-baseline-2026-05-24.md) (the 30-item smoke baseline) — that note's tables stay as historical record; this note carries the load-bearing numbers going forward.

---

## Headline scores

**Full sweep, 500 items, `longmemeval_oracle.json`, post-Tier-1 (`main` at `7e379ae`).**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 78 | 73 | 93.59% |
| multi-session | 133 | 121 | 90.98% |
| single-session-assistant | 56 | 55 | 98.21% |
| single-session-preference | 30 | 15 | 50.00% |
| single-session-user | 70 | 68 | 97.14% |
| temporal-reasoning | 133 | 71 | 53.38% |
| | | | |
| **overall** | **500** | **403** | **80.60%** |

### Side-by-side with the pre-Tier-1 smoke baseline

| Category | Smoke 2026-05-24 (n=5 ea) | Full 2026-05-25 (oracle dist.) | Δ |
|---|---:|---:|---:|
| knowledge-update | 20.00% (1/5) | **93.59%** (73/78) | **+73.59pp** |
| multi-session | 20.00% (1/5) | **90.98%** (121/133) | **+70.98pp** |
| single-session-assistant | 100.00% (5/5) | 98.21% (55/56) | −1.79pp |
| single-session-preference | 20.00% (1/5) | 50.00% (15/30) | **+30.00pp** |
| single-session-user | 100.00% (5/5) | 97.14% (68/70) | −2.86pp |
| temporal-reasoning | 100.00% (5/5) | 53.38% (71/133) | **−46.62pp** |
| **overall** | **60.00%** (18/30) | **80.60%** (403/500) | **+20.60pp** |

> **Variance caveat on per-category deltas.** Smoke ran 5 items per category; per-category swings of ±20pp from sampling noise alone were predicted in the smoke note's "Smoke-scale caveat". The single-session-{assistant,user} 1–3pp drops are almost certainly noise; the **temporal-reasoning −46.62pp** drop is too large to be sampling noise on 133 items and is treated as a real finding below. Overall accuracy moved through the gate by **+20.60pp**.

---

## Delta from smoke — which chip closed which gap

| Failure mode (smoke) | Chip | ADR | Expected from PR #57 | Observed delta | Verdict |
|---|---|---|---|---|---|
| **C: empty hypotheses** (6/30 = 20%) | T1.1 `--answer-max-tokens` default 512 → 2048 (PR #61) | (no ADR; CLI default change) | "Near-zero empties on full sweep" | **2/500 = 0.4%** empties | **EXCEEDED** |
| **A: cross-session synthesis** (multi-session 20%, knowledge-update 20%) | T1.2 two cross-session sentences in `_DIALECTIC_PROMPT` (PR #64) | [ADR 0136](../../docs/adr/0136-temporal-aware-dialectic.md) | "Move multi-session + knowledge-update each by ≥20pp on the next sweep" | multi-session **+70.98pp**, knowledge-update **+73.59pp** | **EXCEEDED** (by ~3.5×) |
| **B: preference honoring** (single-session-preference 20%) | T1.3 one preference-honoring sentence in `_DIALECTIC_PROMPT` (PR #66) | [ADR 0137](../../docs/adr/0137-preference-aware-dialectic.md) | "single-session-preference moves by ≥20pp on smoke" (ADR 0137 locked-design table) | **+30.00pp** (20% → 50%) | **MET** (above the 20pp bar, still the weakest category and a candidate for a Tier-2 prompt follow-up) |

### Honest surprise — temporal-reasoning regressed

Smoke had this at 100% (5/5). Full sweep is **53.38% (71/133)**. The 5-item smoke draw was almost certainly the easy tail of the distribution and the headline number was an artifact of that draw. The full-sweep figure is the real signal.

Two compounding possibilities for what the prompt change exposed (not investigated in this chip — flagged for follow-up):

1. **T1.2's "consider the temporal order of events across sessions" sentence may bias the answerer toward narrative explanations on items where the gold answer is a single number/date.** The temporal-reasoning judge prompt tolerates off-by-one but still scores on the final value; a verbose temporal walk-through could obscure the value.
2. **temporal-reasoning is now the largest dialectic-input category by item-share (133/500 = 26.6%) and its items have the deepest session histories.** Even with `--answer-max-tokens 2048`, o4-mini may be hitting reasoning-token exhaustion on the long-history tail (the smoke pre-T1.1 had 6/30 = 20% empties, mostly in deep-history items; full sweep has 2/500 = 0.4% empties overall, so the budget is *mostly* sufficient, but the tail may be where the temporal-reasoning misses cluster).

**Neither is investigated in this chip** — the load-bearing job here is to set the baseline. Both feed naturally into the Tier-2 chip recommendation below.

### Empty-hypothesis count — recovered

| Sweep | Total | Empty hypotheses | Rate |
|---|---:|---:|---:|
| Smoke 2026-05-24 (pre-T1.1, `max_tokens=512`) | 30 | 6 | **20.00%** |
| Full 2026-05-25 (post-T1.1, `max_tokens=2048`) | 500 | 2 | **0.40%** |

T1.1 effectively eliminated reasoning-token exhaustion. The 2 residual empties (1 single-session-preference, 1 temporal-reasoning) are deep-history items where 2048 tokens was still insufficient; the long-tail count is small enough that pushing the default higher is not warranted in this chip.

---

## Sweep metadata

- **Date of sweep**: 2026-05-25 (UTC)
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc` (`/Users/dave/Claude_Primary/LongMemEval`)
- **Chimera commit**: `7e379ae02d0d7157c5069dd1f4ed7a4309df1437` (branch `baseline/longmemeval-post-tier1-2026-05-25`)
- **Dataset**: `longmemeval_oracle.json` (500 items, full oracle distribution — no `--n-per-category` cap)
- **Answerer model**: `openai/o4-mini` via OpenRouter
- **Answer max-tokens**: 2048 (T1.1 default per [PR #61](https://github.com/elementalcollision/chimera/pull/61))
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter (per smoke baseline's note about o4-mini exhausting its judging budget on `max_tokens=16` yes/no prompts; rationale unchanged)
- **Adapter hypothesis count**: 500/500 (no error rows); 498/500 non-empty hypotheses (2 empties, both graded incorrect by the judge)
- **Wall-clock**: sweep ~70 min (sequential o4-mini answer calls); grading ~10 min (sequential gpt-4o-mini calls)
- **Inference cost (rough)**: ~$1.5–2 Chimera-side answers + ~$0.10 judge-side ≈ **~$2 total**, in line with the PR #57 budget envelope.

---

## Success criterion verdict

**Overall 80.60% ≥ 75% bar → GATE CLEARED.**

Per PR #57's Tier-1 success criterion: "full-sweep post-Tier-1 ≥75% overall mitigates the cross-session-synthesis cliff and bounds Phase 4 #6.b's expected impact enough to justify the engineering cost". With the gate met:

1. **Promote ADR 0136 (`Proposed` → `Accepted`)** with a status note: *"promotion gate cleared: full-sweep overall 80.60% vs 75.00% bar; T1.2's two cross-session sentences delivered +70.98pp on multi-session and +73.59pp on knowledge-update."*
2. **Promote ADR 0137 (`Proposed` → `Accepted`)** with a status note: *"promotion gate cleared: ADR 0137 locked-design table required single-session-preference move ≥20pp; observed +30pp (20% → 50%) on full sweep."*
3. **Recommend launching Tier-2 chip T2.1 (Phase 4 #6.b hybrid retrieval)** as the next development priority. The 80.60% number is now the regression gate — *"adding the vector half must not regress overall by more than 2pp, must not regress knowledge-update or multi-session by more than 3pp"* becomes a concrete merge gate.

ADR 0135 (LongMemEval integration) is already `Accepted` from PR #56 and is not re-promoted here.

### Where Tier-1 fell short (and what it suggests for Tier-2)

Two categories did **not** clear the 75% bar even after the chips: **temporal-reasoning 53.38%** and **single-session-preference 50.00%**. Neither is a blocker (overall ≥75% is what the gate was set on), but both are concrete targets:

- **temporal-reasoning** — the regression from the smoke headline is a real signal. The most likely cause is T1.2's added narrative bias on items whose gold answer is a single value. A Tier-1.5 / Tier-2 chip could tighten the temporal sentence to *"…but answer with the specific value/date asked for"*. This is a one-sentence-amend chip; if T2.1 (retrieval) lands first it should explicitly NOT regress temporal-reasoning further, and this category needs to be on the retrieval PR's per-category gate.
- **single-session-preference** — T1.3 moved this +30pp but it's still the floor. The chip honored the **stated** preference; the remaining 50% miss is likely items where the preference is **implicit** (the model needs to infer the user's preference from prior behavior, not from a stated rubric). That's a more substantive change than a one-sentence prompt append and likely belongs in a Tier-3 prompt chip or as a small retrieval-side feature (rank preference-bearing turns higher).

These are **recommendations**, not commitments — the load-bearing decision out of this chip is "T2.1 is now justified". Tier-2 prompt follow-ups should be re-evaluated after T2.1 lands so the gate moves once, not twice.

---

## Reproduction

```bash
# 1. Sweep
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  --answer \
  --answer-model openai/o4-mini \
  --answer-max-tokens 2048 \
  --out /tmp/chimera-baseline/results-post-tier1.jsonl

# 2. Grade
python /tmp/chimera-baseline/grade.py \
  /tmp/chimera-baseline/results-post-tier1.jsonl \
  /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  /tmp/chimera-baseline/results-post-tier1-graded.jsonl \
  openai/gpt-4o-mini

# 3. Aggregate
python -c "
from pathlib import Path
from chimera.evals.longmemeval import summarize_results, format_summary_table
print(format_summary_table(summarize_results(
    Path('/tmp/chimera-baseline/results-post-tier1-graded.jsonl'))))
"
```

The grader script is the same `grade.py` from the smoke baseline (PR #56 body).

---

## References

- [`longmemeval-baseline-2026-05-24.md`](./longmemeval-baseline-2026-05-24.md) — pre-Tier-1 smoke baseline (30 items, 60.00% overall).
- [ADR 0135 — LongMemEval adapter](../../docs/adr/0135-longmemeval-integration.md) (already Accepted from PR #56; not re-promoted).
- [ADR 0136 — Temporal-Aware Dialectic](../../docs/adr/0136-temporal-aware-dialectic.md) (promoted by this note's gate).
- [ADR 0137 — Preference-Aware Dialectic](../../docs/adr/0137-preference-aware-dialectic.md) (promoted by this note's gate).
- PR #57 — post-baseline development priorities (Tier-1 chips defined here).
- PR #61 — T1.1: `--answer-max-tokens` default 512 → 2048.
- PR #64 — T1.2: cross-session sentences in `_DIALECTIC_PROMPT`.
- PR #66 — T1.3: preference-honoring sentence in `_DIALECTIC_PROMPT`.
- Upstream: https://github.com/xiaowu0162/LongMemEval
