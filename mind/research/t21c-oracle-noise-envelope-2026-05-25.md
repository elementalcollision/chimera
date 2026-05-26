# T2.1c — o4-mini single-sweep noise envelope on the LongMemEval oracle 500-item baseline

**Date**: 2026-05-25
**Status**: Decisive (one rerun sufficient)
**Author**: Chimera-Agent
**Scope**: Measurement-only. Characterizes the variance of the o4-mini answerer on byte-identical-input LongMemEval oracle sweeps. **No code or adapter changes.**

## TL;DR

| Run | Commit | Overall | Δ vs baseline |
|---|---|---:|---:|
| Post-T1.5 baseline | `14192658` | **90.80%** | — |
| T2.1b (effective no-op¹) | `662bdf2` | **89.20%** | **−1.60pp** |
| **T2.1c rerun 1** | `1f63335` | **90.40%** | **−0.40pp** |
| **Mean ± stdev (n=3)** | | **90.13% ± 0.83pp** | — |
| **Proposed widened gate** (mean − 2σ) | | **88.47%** | — |

¹ T2.1b's PR #86 failure-mode diagnostic proved every oracle item takes the `len(history) ≤ top_k` no-op branch, making T2.1b's dialectic prompt byte-identical to baseline. Treated as a control sample, not an intervention.

**Headline findings:**

1. Rerun 1 lands in the **decisive band** per the pre-registered rule (|Δ| ≤ 0.5pp): T2.1b's −1.60pp drop is consistent with single-sample tail variance, **not** a real regression.
2. Knowledge-update **fully reproduces baseline** (96.15% vs 96.15%); all 6 KU items T2.1b "lost" were recovered. The −7.69pp KU drag T2.1b saw was a one-shot tail draw.
3. Single-session-preference is the **dominant variance contributor** (σ = 5.09pp across runs). Knowledge-update is second (σ = 4.44pp). Other categories are tight (σ ≤ 2.2pp).
4. **Recommendation**: widen the future "no regression" gate from the 90.80% point estimate to **`mean − 2σ` = 88.47%**.

## Pre-registered decision rules (locked at chip start)

From T2.1b's recommendation §"Follow-up chips":

- **One rerun is sufficient if decisive.** Decisive = |Δ| ≤ 0.5pp (noise floor) OR |Δ| > 2pp (real defect).
- **Second rerun is operator-gated** if the first lands in the ambiguous ±0.5–2pp band.
- **Gate widening criterion**: if mean across reruns is within ±1pp of 90.80% AND stdev (including T2.1b) is ≥ 0.5pp, the future "no regression" gate widens to `baseline_mean − 2σ`.

**Outcome**: Rerun 1 = 90.40%, |Δ| = 0.40pp → decisive band. No second rerun launched. Both gate-widening preconditions met (mean 90.13% within ±1pp; σ = 0.83pp ≥ 0.5pp). **Gate widens.**

## Per-category accuracy (3 runs)

| Category | Baseline | T2.1b | Rerun1 | Mean | σ | Range |
|---|---:|---:|---:|---:|---:|---:|
| knowledge-update | 96.15% (75/78) | 88.46% (69/78) | **96.15% (75/78)** | 93.59% | 4.44pp | 88.46–96.15 |
| multi-session | 90.23% (120/133) | 89.47% (119/133) | 87.97% (117/133) | 89.22% | 1.15pp | 87.97–90.23 |
| single-session-assistant | 100.00% (56/56) | 98.21% (55/56) | 98.21% (55/56) | 98.81% | 1.03pp | 98.21–100.00 |
| single-session-preference | 46.67% (14/30) | 43.33% (13/30) | 36.67% (11/30) | 42.22% | 5.09pp | 36.67–46.67 |
| single-session-user | 98.57% (69/70) | 100.00% (70/70) | 98.57% (69/70) | 99.05% | 0.82pp | 98.57–100.00 |
| temporal-reasoning | 90.23% (120/133) | 90.23% (120/133) | 93.98% (125/133) | 91.48% | 2.17pp | 90.23–93.98 |
| **OVERALL** | **90.80% (454/500)** | **89.20% (446/500)** | **90.40% (452/500)** | **90.13%** | **0.83pp** | **89.20–90.80** |

## Pairwise item-level flip matrices

500 questions; flip = `is_correct` changes between two runs (byte-identical input).

| Pair | Both right | Both wrong | Only A right | Only B right | Net |
|---|---:|---:|---:|---:|---:|
| baseline (A) vs T2.1b (B) | 432 | 32 | 22 | 14 | +8 baseline |
| baseline (A) vs rerun1 (B) | 439 | 33 | 15 | 13 | +2 baseline |
| T2.1b (A) vs rerun1 (B) | 438 | 40 | 8 | 14 | −6 (T2.1b favored) |

**Per-pair flip count** (right→wrong + wrong→right):

- baseline ↔ T2.1b: **36 flips** (7.2% of corpus)
- baseline ↔ rerun1: **28 flips** (5.6% of corpus)
- T2.1b ↔ rerun1: **22 flips** (4.4% of corpus)

Even when overall accuracy is identical to within 0.40pp, **5–7% of items flip identity**. Aggregate accuracy is noticeably more stable than per-item determinism. This matters for the n=30 spike methodology: at category=30, a 5.6% flip rate means ~1.7 items per spike are inherently non-deterministic.

## Knowledge-update specifically: T2.1b was a tail draw

The most alarming T2.1b signal was the −7.69pp drag on knowledge-update (78 items, 6 items lost). The fear: hybrid retrieval was subtly harming knowledge-update items even on the no-op code path. **This chip falsifies that fear.**

| Pair | KU items lost | KU items gained | Net |
|---|---:|---:|---:|
| baseline → T2.1b | 6 | 0 | **−6** |
| baseline → rerun1 | 2 | 2 | **0** |
| T2.1b → rerun1 | 0 | 6 | **+6** |

Crucially: **all 6 KU items T2.1b lost vs baseline were recovered by rerun1.** This is the diagnostic signature of single-sample variance, not a directional effect. If T2.1b's dialectic-prompt code path had truly perturbed KU answerer behavior, those same items would have been lost again on rerun1 (which runs the identical code path).

## Variance is category-localized

The corpus-wide σ = 0.83pp masks **highly heterogeneous per-category variance**:

| Variance rank | Category | σ (pp) | n | Implied per-item noise² |
|---|---|---:|---:|---:|
| 1 | single-session-preference | 5.09 | 30 | ~1.5 flipping items per run |
| 2 | knowledge-update | 4.44 | 78 | ~3.5 flipping items per run |
| 3 | temporal-reasoning | 2.17 | 133 | ~2.9 flipping items per run |
| 4 | multi-session | 1.15 | 133 | ~1.5 flipping items per run |
| 5 | single-session-assistant | 1.03 | 56 | ~0.6 flipping items per run |
| 6 | single-session-user | 0.82 | 70 | ~0.6 flipping items per run |

² Rough estimate: σ × n / 100.

**Interpretation**: the categories where the answerer hovers around a hard boundary (SPP at ~40%, KU borderline cases) are the noisiest. Categories where the answerer is either confidently right (SSA, SSU at ~99%) or steadily mid (multi-session at ~89%) are tighter. SPP's σ = 5.09pp on n=30 means **the noise floor on T2B-style 30-item SPP spikes is ±5pp**, which is roughly the magnitude of the intervention deltas the prior Tier-2B investigation was chasing.

## Implications

### 1. Gate-widening: future "no regression" criterion is `mean − 2σ = 88.47%`

Going forward, any chip claiming "oracle no-regression" should clear **≥ 88.47% overall** on a single 500-item sweep, not "≥ 90.80%". This widens the gate by 2.33pp, but it is honest about the measurement substrate.

A more conservative formulation (matching ADR 0140's dual-gate spirit) would also require **per-category clearance at `mean − 2σ`**:

| Category | Mean − 2σ gate |
|---|---:|
| knowledge-update | 84.71% |
| multi-session | 86.92% |
| single-session-assistant | 96.75% |
| **single-session-preference** | **32.04%** |
| single-session-user | 97.41% |
| temporal-reasoning | 87.14% |

Note: SPP's gate floor is **32.04%**, reflecting its 5pp σ on a 30-item base. Future SPP interventions must clear this conservatively, or use a corpus-wide sweep where SPP weight is diluted by 470 other items.

### 2. ADR 0142's `_s`-only verdict: defensibly conservative, not a hard line

T2.1b's 89.20% sits **0.73pp above** the proposed `mean − 2σ` floor (88.47%). Under the widened envelope, T2.1b's failure was not a regression; it was a single-sample landing in the lower tail.

**Per chip charter, ADR 0142's status is not modified by this chip.** This note is recorded so a future operator decision can revisit "Accepted (`_s`-only)" → "Accepted (full)" if desired, with this envelope as the supporting evidence. That decision is out of scope here.

### 3. T2.1d (deterministic answerer) is now warranted, not moot

The chip charter asked whether T2.1d (deterministic-answerer pivot) is "now warranted or moot." **Warranted.** Reasons:

- 5.6% item-flip churn on byte-identical input means n=30 spike methodology has ~1.7 items of irreducible noise per spike. Most interventions the prior investigations chased are below this threshold.
- SPP σ = 5.09pp on n=30 dwarfs the typical intervention effect size (PR #75 implicit-preference heuristic was ~3pp on its respike).
- A temperature=0 / seed-locked answerer would not necessarily eliminate variance (o4-mini reasoning models are not fully deterministic), but it bounds it. The marginal cost is low; the methodology gain is large.

**Recommendation**: charter T2.1d as the next chip after this lands. Scope: investigate whether o4-mini supports a deterministic / seeded mode through OpenRouter, and if not, evaluate fallback to a temperature=0 non-reasoning model (e.g. gpt-4o-mini) as the answerer for evaluation-substrate sweeps only.

### 4. The 30-item spike methodology limits are now quantified

ADR 0138's n=30 spike protocol and ADR 0140's stratified refinement both implicitly assumed sub-percent per-item noise. The data show SPP-class noise at ±5pp per 30-item slice. **The stratified spike protocol (ADR 0140) is the correct conservative response**; this chip's data validates its premise empirically.

## Operational details

### Rerun 1 invocation

```bash
.venv/bin/chimera evals longmemeval \
    --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
    --answer --answer-model openai/o4-mini --answer-max-tokens 2048
```

**No `--hybrid-retrieval` flag** → default `hybrid_retrieval=False`. Identical configuration to baseline.

Result file: `/tmp/chimera-t21c-rerun1/results.jsonl` (also archived from the CLI's autosaved path `mind/evals/longmemeval-20260526T025137Z.jsonl`). Sweep wall-clock: ~52 min. Estimated spend: ~$2.

### Grading

```bash
.venv/bin/python /tmp/chimera-baseline/grade.py \
    /tmp/chimera-t21c-rerun1/results.jsonl \
    /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
    /tmp/chimera-t21c-rerun1/results.graded.jsonl \
    openai/gpt-4o-mini
```

**Grader pitfall**: `grade.py`'s default judge is `openai/o4-mini`, but the post-T1.5 baseline and T2.1b both used `openai/gpt-4o-mini` (per the `autoeval_label.model` field in their `.graded.jsonl`). The o4-mini judge returns empty content under the grader's `max_tokens=16` budget (likely consumed by reasoning channel). Initial grade attempt produced 0/500 across the board; re-grading with the explicit `openai/gpt-4o-mini` arg reproduced the correct comparison substrate. **Recommendation**: a follow-up housekeeping chip should change `grade.py`'s default judge to `openai/gpt-4o-mini` to prevent this footgun. (Not in scope here.)

## Followups

- **T2.1d** — deterministic answerer pivot (charter above). Recommended next.
- **Grade.py default judge fix** — change default from `openai/o4-mini` to `openai/gpt-4o-mini`. Trivial.
- **Optional T2.1e** — second oracle rerun to tighten σ. Per the locked decision rule this was not required (rerun 1 was decisive), but a third independent sample would tighten the σ estimate from 0.83pp (n=3) toward the true value. Operator-gated; ~$2 / ~55 min.

## Artifacts

- Rerun 1 raw: `/tmp/chimera-t21c-rerun1/results.jsonl`
- Rerun 1 graded: `/tmp/chimera-t21c-rerun1/results.graded.jsonl`
- Rerun 1 sweep log: `/tmp/chimera-t21c-rerun1/sweep.log` (empty — Python stdout buffering until exit; CLI banner went to the redirected stdout file)
- Rerun 1 grade log: `/tmp/chimera-t21c-rerun1/grade.log`
- Baseline (comparison): `/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl`
- T2.1b (comparison): `/tmp/chimera-t21b-oracle/results.graded.jsonl`
- CLI autosave: `mind/evals/longmemeval-20260526T025137Z.jsonl`

## Linked decisions

- [T2.1b oracle no-regression note](./t21b-oracle-no-regression-2026-05-25.md) — the chip that surfaced the noise hypothesis
- [Post-T1.5 baseline note](./longmemeval-baseline-post-t1.5-2026-05-25.md) — the 90.80% point estimate this chip widens
- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid retrieval; verdict not modified by this chip
- [ADR 0143](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) — this chip's noise-envelope decision (new)
