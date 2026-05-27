# F2 — LoCoMo hybrid-retrieval ablation

**Date**: 2026-05-27
**Status**: Complete — MIXED (per-category outcome, see §Verdict)
**Chip**: F2 — hybrid-retrieval ablation against F1 LoCoMo baseline
**Predecessors**:
- [F1 baseline](./locomo-baseline-full-2026-05-26.md) — 49.35% overall, 1,986-item ground truth
- [F3 noise envelope](./locomo-noise-envelope-2026-05-27.md) — σ=0.46pp overall; locked gates from ADR 0145
- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid-retrieval decision (+56.67pp on LME `_s`)
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — gate authority

## TL;DR

**VERDICT**: **MIXED** (see §Locked-outcome verdict for rule-conflict disclosure).

Hybrid retrieval (`--hybrid-retrieval --retrieval-top-k 8`) on LoCoMo's 1,986-item full corpus shifts overall accuracy from **49.35% → 59.37%** (**+10.02pp**), with three categories clearing the ADR 0145 "improves" bar by huge margins (adversarial +20.63pp, multi-hop +16.82pp, open-domain +7.61pp), **one category clearing the "harms" bar** (temporal-reasoning −10.42pp, 35.42% < 43.94% gate), and one category in-envelope (single-hop −0.35pp). The pattern is asymmetric per category; not monolithic. The +10pp overall is real (~22× the F3 overall σ=0.46pp), but the temporal-reasoning regression is also real (>2× any plausible per-cat noise envelope at n=96).

## Side-by-side F1 vs F2 per-category table

| Category | F1 | F2 | Δ |
|---|---:|---:|---:|
| adversarial (n=446) | 12.33% (55) | **32.96%** (147) | **+20.63pp** |
| multi-hop (n=321) | 28.97% (93) | **45.79%** (147) | **+16.82pp** |
| open-domain (n=841) | 77.88% (655) | **85.49%** (719) | **+7.61pp** |
| single-hop (n=282) | 47.16% (133) | 46.81% (132) | −0.35pp |
| temporal-reasoning (n=96) | 45.83% (44) | **35.42%** (34) | **−10.42pp** |
| **OVERALL (n=1986)** | **49.35% (980)** | **59.37% (1,179)** | **+10.02pp** |

## Per-category gate clearance

Pre-registered gates (LOCKED from ADR 0145 — no recomputation):

| Category | F1 | Improves if | Harms if | F2 | Improves? | Harms? |
|---|---:|---:|---:|---:|:---:|:---:|
| adversarial | 12.33% | > 13.27% | < 11.55% | 32.96% | **YES** (+19.69pp over bar) | no |
| multi-hop | 28.97% | > 29.69% | < 28.04% | 45.79% | **YES** (+16.10pp over bar) | no |
| open-domain | 77.88% | > 78.72% | < 76.61% | 85.49% | **YES** (+6.77pp over bar) | no |
| single-hop | 47.16% | > 50.52% | < 41.92% | 46.81% | no | no (in envelope) |
| temporal-reasoning | 45.83% | > 47.03% | < 43.94% | 35.42% | no | **YES** (−8.52pp under bar) |
| **OVERALL** | **49.35%** | **> 50.27%** | **< 47.94%** | **59.37%** | **YES** (+9.10pp over bar) | no |

**Summary**: 3 categories clear IMPROVES (by 7–20pp), 1 category clears HARMS (by 8.5pp), 1 category in-envelope. OVERALL clears IMPROVES by ≥9pp.

## Locked-outcome verdict

Outcome bands (from charter / ADR 0145):

- **HELPS**: overall > F1+0.92pp AND ≥2/5 categories clear "improves" AND no category clears "harms".
- **HURTS**: overall < 47.94% OR any category clears "harms".
- **IN-ENVELOPE NOISE**: overall delta inside ±2σ AND no category clears either bar.
- **MIXED**: some help, others hurt.

### Strict-rule ambiguity

The 1,986-item data triggers **two** outcome bands as written:

- **HELPS** is blocked because temporal-reasoning clears the harms gate (the rule requires "no category clears harms").
- **HURTS** is triggered by the temporal-reasoning category clearing the harms bar (the rule says "OR any harms clear"). But "HURTS" would imply hybrid retrieval was a net loss — and the +10.02pp overall (≥10× the +0.92 improves bar, ~22× the F3 σ=0.46pp envelope) plus three categories at +7 to +20pp clearly falsify that empirical claim.
- **IN-ENVELOPE NOISE** is precluded — the +10.02pp overall is ~22× the F3 noise envelope.
- **MIXED** literally describes the data: "some help, others hurt" — three improves clear, one harms clears, one in-envelope.

### Resolution: **MIXED**

Picking MIXED for three reasons:

1. **Empirical fit**: The data is asymmetric per category. "MIXED" is the outcome band designed exactly for this case ("some help, others hurt").
2. **HURTS would be empirically false**: A +10pp overall improvement with three categories clearing IMPROVES by 7–20pp is not a "hurts" result; the literal rule trigger ("any category clears harms") was clearly written assuming the overall-harms branch (overall < 47.94%) would co-fire. Here the overall is +10pp above F1, ≥9pp above the IMPROVES bar.
3. **Charter discipline**: Operator's MIXED band exists precisely to avoid forcing a binary HELPS/HURTS in the face of category asymmetry. Per ADR 0145's design intent ("record per-category verdicts; no global helps/hurts claim"), MIXED is the correct landing.

**Operator may reclassify on PR review.** The rule-as-written conflict is real and worth surfacing rather than papering over.

## Item-level flip analysis

Per-item flips F1↔F2 across all 1,986 items:

| Category | n | both right | both wrong | only F1 right | only F2 right | flips | flip % | net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| adversarial | 446 | 44 | 288 | 11 | 103 | 114 | 25.56% | +92 |
| multi-hop | 321 | 72 | 153 | 21 | 75 | 96 | 29.91% | +54 |
| open-domain | 841 | 620 | 87 | 35 | 99 | 134 | 15.93% | +64 |
| single-hop | 282 | 96 | 113 | 37 | 36 | 73 | 25.89% | **−1** |
| temporal-reasoning | 96 | 25 | 43 | 19 | 9 | 28 | 29.17% | **−10** |
| **OVERALL** | **1986** | **857** | **684** | **123** | **322** | **445** | **22.41%** | **+199** |

### Oscillation vs F3 noise envelope

F3 measured single-sweep oscillation on byte-identical input (σ overall = 0.46pp, σ single-hop = 1.68pp). F2 deltas are outside that envelope for **four of five categories**:

- adversarial: +20.63pp ≫ any plausible per-cat σ at n=446 → real signal.
- multi-hop: +16.82pp ≫ any plausible per-cat σ at n=321 → real signal.
- open-domain: +7.61pp ≫ any plausible per-cat σ at n=841 → real signal.
- temporal-reasoning: **−10.42pp** ≫ any plausible per-cat σ at n=96 → real regression. (For comparison: F3's loudest category single-hop has σ=1.68pp at n=282 — temporal-reasoning at n=96 cannot plausibly have σ > ~3pp.)
- single-hop: −0.35pp is well inside F3's σ=1.68pp single-hop band → in-envelope.

Overall +10.02pp is ~22× the F3 σ=0.46pp overall envelope. This is not noise.

### Flip volume

- 445 flips total (22.41% of items oscillate F1 vs F2). For comparison, F3 measured ~92 flips/pair on byte-identical input (~4.6% flip floor from answerer stochasticity alone). F2's 22.41% flip rate is ~5× the byte-identical floor.
- ~72% of flips are structurally additive (322 only-F2-right vs 123 only-F1-right → net +199).
- temporal-reasoning is the **only** category where F1-only-right exceeds F2-only-right (19 vs 9 → net −10). The regression is structural, not redistributive.

## Cross-benchmark synthesis vs ADR 0142

ADR 0142's `_s` result: **+56.67pp** (10.00% → 66.67%) on LongMemEval `_s` long-horizon (n=30 stratified, BM25-only in practice, o4-mini answerer).

ADR 0142's oracle T2.1b result: **−1.60pp gate failure** (89.20% vs 90.80% floor), with knowledge-update at −7.69pp — but every oracle item is ≤8 sessions so the retrieval layer is a structural no-op, and the diagnostic concluded the failure was o4-mini single-sweep noise.

LoCoMo conversations are 19–32 sessions. The retrieval layer is structurally active on every item (not a no-op pass-through like oracle).

**Cross-benchmark concordance**:

| Benchmark | Variant | Category surface | Hybrid retrieval | Substrate | Verdict |
|---|---|---|---:|---|---|
| LongMemEval | `_s` | multi-session, knowledge-update, single-session-{user,assistant,preference}, temporal-reasoning | **+56.67pp** | o4-mini | HELPS (ADR 0142 accepted `_s`-only) |
| LongMemEval | oracle | same categories, ≤3 sessions | −1.60pp (structural no-op + noise) | o4-mini | GATE-UNTESTED |
| LoCoMo | full corpus | adversarial, multi-hop, open-domain, single-hop, temporal-reasoning | **+10.02pp overall; per-category asymmetric** | gpt-4o-mini | MIXED |

**The retrieval intervention is not monolithic across benchmarks or categories.** Where there's a haystack-vs-collapsed-context win (LongMemEval `_s`), retrieval rescues collapsed accuracy. On LoCoMo where the baseline is healthy (49.35%) and conversations have 19–32 sessions, retrieval helps four cells (overall + three categories) but hurts temporal-reasoning. The temporal-reasoning regression is a new finding worth a follow-up investigation (see §Recommended follow-up).

## Honest disclosures

1. **Single-sweep caveat (F2 itself)**: F2 is one sweep. There is no σ for F2 specifically — the F3 envelope (σ=0.46pp overall, σ=1.68pp single-hop) bounds interpretation. The +10.02pp overall is ~22× σ and the −10.42pp temporal-reasoning regression is ≫ any plausible n=96 per-cat σ, so the headline signals survive single-sweep caveats. Within-envelope deltas (single-hop −0.35pp) cannot be distinguished from noise.

2. **Substrate confound (gpt-4o-mini vs o4-mini)**: F2 uses `gpt-4o-mini` (non-reasoning, same as F1/F3). The LongMemEval `_s` win used `o4-mini` (reasoning). Cross-benchmark magnitudes are not directly comparable between F2 LoCoMo and ADR 0142's `_s` result; what is comparable is **the directional sign on shared categories**, and both are positive overall. The category-level asymmetry on LoCoMo is the cleaner signal for gpt-4o-mini specifically.

3. **Conservative-gate worst-case**: The "improves" column requires F1 + 2σ — symmetric to the harms gate. Any per-category delta between the two thresholds is definitionally in-envelope noise at the n=1-sweep level. Single-hop (−0.35pp) lands here.

4. **BM25-only fallback events: 0** logged in `sweep.log`. All 1,986 items ran with the full BM25 + dense Ollama bge-m3 retrieval stack active. Unlike ADR 0142's `_s` runs (Voyage rate-limited → BM25-only in practice), this F2 sweep is a true BM25+dense result.

5. **Answer-timeout (`asyncio.wait_for(..., 240s)`) events: 0** items hit the PR #97 belt-and-suspenders bound. No items lost to wait_for timeouts. The post-PR-#97 persistent-loop stability held cleanly across all 10 conversation boundaries.

6. **Slow-embed warnings**: 10 PR #96 "slow Ollama embed" warnings (>15s for an embed batch). All completed without escalation to BM25-fallback. These are degradation-floor notices, not failure events.

7. **Sweep wall time**: 3 h 41 min (18:22:17Z → 22:03:38Z), 10/10 conversations completed cleanly, 0 answer errors, 0 wait_for timeouts, 0 BM25-fallback events, 10 benign slow-embed warnings. Total API spend: ~$8, within authorized $9 budget.

## Operational details

### Substrate

- **Answerer**: `openai/gpt-4o-mini`, temperature 0, max_tokens 2048
- **Flags**: `--hybrid-retrieval --retrieval-top-k 8`
- **Judge**: `openai/gpt-4o-mini`, max_tokens=16 (same as F1/F3)
- **Corpus**: `/tmp/locomo/locomo10.json`, all 1,986 QA pairs across 10 conversations
- **Grader**: `scripts/grade_locomo.py` default (no judge override)

### Invocation

```bash
CHIMERA_LOCOMO_TRACE=1 PYTHONUNBUFFERED=1 chimera evals locomo \
  --items /tmp/locomo/locomo10.json \
  --answer --answer-model openai/gpt-4o-mini \
  --answer-temperature 0 --answer-max-tokens 2048 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-f2-locomo-v6/results.jsonl \
  --mind-dir /tmp/chimera-f2-locomo-v6/mind
```

### Artifacts

- Raw JSONL: `/tmp/chimera-f2-locomo-v6/results.jsonl` (1,986 lines)
- Graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl` (1,986 lines)
- Sweep log: `/tmp/chimera-f2-locomo-v6/sweep.log`
- Grading log: `/tmp/chimera-f2-locomo-v6/grade.log`

## Recommended follow-up

The temporal-reasoning regression (−10.42pp, 19 only-F1-right vs 9 only-F2-right) deserves a dedicated investigation. Three competing hypotheses:

1. **Retrieval-distractor**: BM25 pulls timestamp-irrelevant sessions when the question asks "when did X happen?", crowding the timestamped session out of top-8.
2. **Context-budget**: top-k=8 sessions crowd the answerer's attention budget; the timestamped session is selected but its temporal anchor gets diluted by the other 7 sessions.
3. **Category-fundamentals**: temporal reasoning may need a different retrieval signal entirely (e.g., date-aware ranking, full chronology preservation).

Suggested next chip: an n=96 temporal-reasoning-only ablation across `--retrieval-top-k ∈ {4, 8, 16, full}` to distinguish (1) from (2), with item-level error analysis on the 28 flipped items.

## Linked decisions

- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid-retrieval decision (this note adds cross-benchmark check)
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — gate authority for this chip
- [F1 baseline note](./locomo-baseline-full-2026-05-26.md) — F1 point estimate
- [F3 noise envelope note](./locomo-noise-envelope-2026-05-27.md) — σ values and gate derivation
