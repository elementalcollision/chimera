# LoCoMo benchmark — full corpus baseline (F1)

**Date**: 2026-05-26
**Chip**: F1 — full LoCoMo sweep follow-up to ADR 0144
**Predecessors**: ADR 0144, [locomo-design-2026-05-26.md](./locomo-design-2026-05-26.md), [locomo-baseline-spike-2026-05-26.md](./locomo-baseline-spike-2026-05-26.md)

## Headline

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| open-domain | 841 | 655 | **77.88%** |
| single-hop | 282 | 133 | 47.16% |
| temporal-reasoning | 96 | 44 | 45.83% |
| multi-hop | 321 | 93 | 28.97% |
| adversarial | 446 | 55 | 12.33% |
| | | | |
| **overall** | **1986** | **980** | **49.35%** |

- Zero adapter errors across 1,986 items.
- Sweep wall-clock: ~4h35min. Grader wall-clock: ~45 min.
- Cost: gpt-4o-mini answerer + judge across ~10K tokens/item ≈ **~$8** total
  (within the operator-authorized F1 budget of $5–10).

## Substrate

- **Answerer**: `openai/gpt-4o-mini`, temperature 0, max_tokens 2048,
  full-context (no retrieval), dialectic prompt assembled via ADR 0133
  against synthetic `mind/peers/self.md` populated by the LoCoMo
  adapter. Same config as the spike.
- **Judge**: `openai/gpt-4o-mini`, max_tokens=16, ADR 0143 default.
- **Corpus**: `data/locomo10.json`, all 10 conversations, all 1,986
  QA pairs. No subset / sample-id filter.
- **Adapter**: ingest cache landed `peers/self.md` once per
  `sample_id`; sibling QAs reused the cached card.

## Per-conversation breakdown

| Conv | Total | Correct | Accuracy |
|---|---:|---:|---:|
| conv-26 | 199 | 100 | 50.25% |
| conv-30 | 105 | 63 | 60.00% |
| conv-41 | 193 | 93 | 48.19% |
| conv-42 | 260 | 119 | 45.77% |
| conv-43 | 242 | 119 | 49.17% |
| conv-44 | 158 | 92 | 58.23% |
| conv-47 | 190 | 91 | 47.89% |
| conv-48 | 239 | 117 | 48.95% |
| conv-49 | 196 | 95 | 48.47% |
| conv-50 | 204 | 91 | 44.61% |

Range 44.61–60.00%, spread 15.39pp. Most conversations cluster in the
47–50% band; conv-30 and conv-44 are mild positive outliers, conv-50
a mild negative one. No single conversation drives the headline.

## Spike-vs-full reconciliation (key finding)

The spike note (n=30, all from conv-26, first 6 per cat) projected
60.00% overall. Full corpus came in at **49.35%** — the spike
overshot by **10.65pp**. The per-category breakdown on conv-26 itself
explains why:

| Category | Spike (n=6, first 6) | conv-26 full (all QAs) | Spike Δ |
|---|---:|---:|---:|
| single-hop | 100.00% | 56.25% (18/32) | **+43.75pp** |
| open-domain | 100.00% | 82.86% (58/70) | +17.14pp |
| temporal-reasoning | 66.67% | 61.54% (8/13) | +5.13pp |
| multi-hop | 16.67% | 24.32% (9/37) | −7.65pp |
| adversarial | 16.67% | 14.89% (7/47) | +1.78pp |

The spike's "first-N-per-category" sampling pulled disproportionately
from the **opening sessions** of conv-26 where single-hop and
open-domain QAs cluster around easy early-conversation facts. The
multi-hop and adversarial spike numbers were close to the conv-26 full
truth (spike's adversarial 16.67% vs full 14.89%; spike's multi-hop
16.67% vs full 24.32%) because those categories distribute more
uniformly through the conversation.

**Lesson for future spike chips**: "first-N-per-category" is a
plumbing sampler, not a representative one. The locked-design rule
(>20% on ≥3/5 cats) was the right gate — it caught wiring, didn't
over-claim quality. The spike note's single-conversation-bias caveat
was the right caveat.

## Comparison anchor (sanity, not a gate)

The LoCoMo paper (Maharana et al. 2024) reports F1 / accuracy for
closed-source models on the full benchmark in the **30–50%** range.
Our **49.35%** lands at the top of that band, which is consistent
with:

1. **LLM-judge leniency**: judge-yes-rate runs ~5–10pp higher than
   token-F1 / EM on equivalent answers (Chimera's own LongMemEval
   experience matches this).
2. **gpt-4o-mini specifically**: not in the paper's published runs
   (paper tested gpt-3.5, gpt-4, claude family, gemini, plus
   open-source LLMs). gpt-4o-mini is a meaningfully stronger model
   than gpt-3.5-turbo and broadly comparable to gpt-4 on short
   reasoning, so a number near the top of the paper's range is
   structurally expected.
3. **Full-context substrate**: matches paper's primary setup; no
   retrieval-induced loss.

The order-of-magnitude match is the load-bearing finding. We are not
trying to reproduce the paper exactly — we are establishing Chimera's
own baseline on LoCoMo under the judge family ADR 0143 already
characterized.

## Per-category structural reading

- **open-domain (77.88%, n=841)**: gpt-4o-mini's world knowledge
  dominates. Many of these questions can be answered without
  consulting the conversation. This is the same finding the paper
  reports (open-domain is the easiest category for strong LLMs).
- **single-hop (47.16%, n=282)**: easier in spirit than multi-hop but
  the full corpus shows it's harder than the spike suggested. Many
  single-hop questions reference details deep in long conversations
  that the answerer can't reliably locate even with full context
  (attention dilution).
- **temporal-reasoning (45.83%, n=96)**: ADR 0136's "today" grounding
  is load-bearing here. The 45.83% number is competitive with the
  paper's reported range (~30–50% for closed models).
- **multi-hop (28.97%, n=321)**: matches the paper's reported
  difficulty exactly. Multi-hop on a long conversation requires
  connecting facts across distant sessions; the full-context answerer
  has the raw material but the chain-of-reasoning step is hard. This
  is a primary candidate for retrieval and dialectic value-add.
- **adversarial (12.33%, n=446)**: gpt-4o-mini rarely refuses on
  LoCoMo's unanswerable questions; confabulation is the default. The
  judge template is strict ("model could say information is
  incomplete" is the only acceptable surface), which is the right
  side of the trade-off for memory eval.

The category ordering (open-domain > single-hop ≥ temporal > multi-hop
> adversarial) matches the paper's reported ordering exactly.

## What this unlocks (chip ladder)

F1 is the no-flag baseline F2/F3/F4 needed. Specifically:

- **F2 — Hybrid-retrieval ablation**: rerun all 1,986 items with
  `--hybrid-retrieval --retrieval-top-k 8` and compare deltas
  category-by-category. ADR 0142's `_s`-only retrieval verdict said
  retrieval *hurts* on short histories (LongMemEval oracle was a
  no-op path; deep `_s` paths benefited). LoCoMo's 19–32 session
  conversations are everywhere above the top-k threshold, so this is
  the cleanest cross-benchmark test of the verdict. F2's headline
  delta lands directly against this baseline.
- **F3 — Noise envelope on LoCoMo**: rerun 2× under byte-identical
  inputs and characterize σ per category, mirroring ADR 0143's T2.1c
  pattern. n=3 mean ± σ for each LoCoMo category. With sample sizes
  here (96–841), the per-category σ should be tighter than
  LongMemEval's small-n SPP envelope of 5.09pp.
- **F4 — Dialectic-shine localisation**: with F1 + LongMemEval
  baselines now both pinned, an A/B between full-context-baseline and
  full-dialectic-with-multi-peer can locate where the dialectic
  pipeline actually adds value vs the model-strength ceiling
  observed in T2.1d.

Best next chip: **F3** first — it's cheap (~2× $8 = $16 cost, two
sweeps without new code) and unlocks the variance vocabulary needed to
read F2 deltas correctly. F2 without F3's σ envelope risks repeating
the T2.1b mistake (rejecting a no-op path on single-sweep noise).

## Caveats

1. **Single-judge dependency**: same judge as LongMemEval
   (`openai/gpt-4o-mini`). σ envelope from ADR 0143 is not yet
   characterized on LoCoMo (F3). Treat per-category accuracy
   point-estimates as such; deltas vs F1 baseline need σ to read.
2. **Full-context only**: hybrid-retrieval ablation is F2.
3. **No dialectic value claim**: this baseline measures "Chimera's
   adapter wiring + the answerer", not "Chimera's dialectic over
   multi-peer". F4 is where that distinction gets tested.
4. **Cost discipline**: F2's rerun will be ~the same $8; F3's two
   reruns ~$16. Operator-gated per existing precedent.

## Verdict on ADR 0144

The spike's directional gate cleared; F1 confirms wiring is
**production-correct**: zero adapter errors across 1,986 items,
category ordering matches the paper, headline accuracy in the
expected band. ADR 0144 remains **Accepted**. §Consequences gets a
new row for the F1 follow-up with the headline number and the F2/F3/F4
chip ladder updated against the now-known baseline.
