# ADR 0145 — LoCoMo noise envelope: future "no regression" gates use `mean − 2σ`

**Status**: Accepted (2026-05-27). Records the noise-envelope characterization from F3.

## Context

The F1 LoCoMo full-corpus baseline of **49.35% / 1,986 items**
(PR #91, commit `ac23301`, see
[locomo-baseline-full-2026-05-26.md](../../mind/research/locomo-baseline-full-2026-05-26.md))
was a **single-sweep point estimate**. Every "no regression" gate that
follows it — F2's hybrid-retrieval ablation, F4's dialectic
localisation, and future LoCoMo-anchored chips — would implicitly
treat 49.35% as the true population mean unless the envelope is
characterised.

[ADR 0143](./0143-longmemeval-oracle-noise-envelope.md) records the
direct methodology twin: a single-sample LongMemEval oracle estimate
at 90.80% was rejecting half of equivalent re-runs because the true
overall σ across byte-identical inputs was 0.83pp. T2.1b (`_s`-only
verdict for hybrid retrieval) was the cost of that mistake. F3 was
chartered to prevent the same failure on LoCoMo before F2 and F4 run
against the F1 point estimate.

F3 (this ADR's source chip) ran two additional byte-identical-input
sweeps on the same current main (`ac23301`) and graded them under the
F1 substrate. Headline:

| Run | Overall | single-hop | open-domain | adversarial | multi-hop | temporal-reasoning |
|---|---:|---:|---:|---:|---:|---:|
| F1 (PR #91) | 49.35% | 47.16% | 77.88% | 12.33% | 28.97% | 45.83% |
| F3 rerun-1 | 48.79% | 44.68% | 77.41% | 13.00% | 28.35% | 44.79% |
| F3 rerun-2 | 48.44% | 43.97% | 77.05% | 12.11% | 28.97% | 44.79% |
| **mean (n=3)** | **48.86%** | **45.27%** | **77.45%** | **12.48%** | **28.76%** | **45.14%** |
| **stdev (n=3)** | **0.46pp** | **1.68pp** | **0.42pp** | **0.47pp** | **0.36pp** | **0.60pp** |

Detail, per-pair flip matrices, and operational details in
[F3 noise-envelope note](../../mind/research/locomo-noise-envelope-2026-05-27.md).

Three structural findings:

1. **Aggregate variance is small.** Overall σ = 0.46pp on three samples;
   range 0.91pp across byte-identical inputs. About **1.8× tighter than
   the LongMemEval o4-mini envelope** (σ = 0.83pp on n=3).
2. **Per-category σ is uniformly tighter than LongMemEval.** Worst
   LoCoMo category is single-hop at σ = 1.68pp on n=282 — vs
   LongMemEval's worst (SPP at σ = 5.09pp on n=30). The tighter
   envelope is partly larger per-category n (LoCoMo categories are
   96–841 items vs LongMemEval's 30–133) and partly the answerer model
   choice (gpt-4o-mini vs o4-mini); the contributions are confounded by
   this data alone and not separately attributable.
3. **Item-level flip rate is 4.58–4.68%** across all 3 pairs — ~92
   LoCoMo items per pair toggle right↔wrong on byte-identical input.
   Same order as LongMemEval (5.6%) but lower.

A point-estimate gate at 49.35% would reject ~half of equivalent
re-runs of the same configuration. This is the wrong failure mode for
F2/F4 — it forces conservative chip verdicts on what may be unbiased
measurement noise.

## Decision

**The "no regression" gate for future LoCoMo full-corpus sweeps is
`mean − 2σ` over the envelope of byte-identical-input reruns, not the
single-sample F1 point estimate.**

### Current envelope (as of 2026-05-27, n=3)

| Scope | Mean | σ | Gate (`mean − 2σ`) |
|---|---:|---:|---:|
| **Overall (n=1986)** | **48.86%** | **0.46pp** | **47.94%** |
| adversarial (n=446) | 12.48% | 0.47pp | 11.55% |
| multi-hop (n=321) | 28.76% | 0.36pp | 28.04% |
| open-domain (n=841) | 77.45% | 0.42pp | 76.61% |
| **single-hop (n=282)** | **45.27%** | **1.68pp** | **41.92%** |
| temporal-reasoning (n=96) | 45.14% | 0.60pp | 43.94% |

A chip claiming "LoCoMo no-regression" must clear **≥ 47.94% overall**
on a single 1,986-item sweep. Per-category clearance against the
per-category gates is recommended (mirrors [ADR 0140](./0140-stratified-spike-protocol.md)'s
dual-gate spirit and the analogous recommendation in
[ADR 0143](./0143-longmemeval-oracle-noise-envelope.md)) but not
required at this ADR's level.

### Symmetric "improves" threshold

For interventions claiming a positive effect, the symmetric `mean +
2σ` threshold (relative to F1 point estimate, or to the current
envelope mean once n≥5) is the structurally honest read:

| Scope | F1 + 2σ (improves) |
|---|---:|
| Overall | > 50.27% |
| single-hop | > 50.52% |
| open-domain | > 78.72% |
| adversarial | > 13.27% |
| multi-hop | > 29.69% |
| temporal-reasoning | > 47.03% |

Deltas inside `[F1 − 2σ, F1 + 2σ]` are envelope noise.

### Envelope update policy

- Each new byte-identical LoCoMo sweep (no `--hybrid-retrieval` flag,
  default `hybrid_retrieval=False`, same answerer and judge) extends
  the envelope. Recompute mean and σ.
- The envelope is **monotonic in n**: σ estimates from n=3 are wide
  confidence intervals (`σ ∈ [~0.23pp, ~0.69pp]` for overall with
  moderate confidence). Once n ≥ 5, σ stabilises and the gate
  tightens automatically.
- When the answerer or grader configuration changes (different
  `--answer-model`, different judge model, different `max_tokens`,
  different temperature), the envelope is **invalidated** and must be
  re-characterised. This includes provider-side silent model rollovers.

## Consequences

### Positive

1. **F2 and F4 are read-ready.** Hybrid-retrieval ablation (F2) and
   dialectic localisation (F4) deltas can now be interpreted against a
   characterised envelope rather than a point estimate. Specifically,
   F2's per-category deltas have explicit "improves" and "harms"
   thresholds:

   | Category | F2 improves if | F2 harms if |
   |---|---:|---:|
   | adversarial | > F1 + 0.94pp | < 11.55% |
   | multi-hop | > F1 + 0.72pp | < 28.04% |
   | open-domain | > F1 + 0.84pp | < 76.61% |
   | single-hop | > F1 + 3.36pp | < 41.92% |
   | temporal-reasoning | > F1 + 1.20pp | < 43.94% |
   | **OVERALL** | **> F1 + 0.92pp** | **< 47.94%** |

2. **T2.1b-class misreadings are mitigated on LoCoMo.** A single-sweep
   −0.55pp draw (as rerun-1 produced here) would have failed a strict
   point-estimate gate but is in-envelope noise. The widened gate
   prevents the rejection-of-no-op-changes failure mode that motivated
   the LongMemEval analogue.

3. **LoCoMo proves the better-resolution benchmark for sub-1pp
   interventions.** Overall σ = 0.46pp here vs 0.83pp on LongMemEval.
   For dialectic-and-retrieval interventions whose expected effect size
   is in the 0.5–1pp range, LoCoMo's envelope makes the signal
   detectable; LongMemEval's would not. Recorded as a benchmark-choice
   factor for future chip charters.

### Negative

1. **n=3 σ is wide.** True σ is somewhere in `[~0.23pp, ~0.69pp]` for
   overall with moderate confidence; the gate at 47.94% may be
   slightly too generous or slightly too tight. Mitigation: the
   envelope is monotonic in n and will tighten as samples accumulate.
2. **Past chip verdicts retain their original status.** This ADR does
   not retroactively flip F1's verdict or modify ADR 0144 substantive
   content; it only records the noise envelope that follows from the
   F1 substrate. F1's headline 49.35% remains the published baseline;
   the envelope governs comparisons against it.
3. **Single-hop has the loudest per-category σ** (1.68pp on n=282).
   Per-category-localised regressions of up to 3.36pp on single-hop
   alone would not clear the gate. Honest about the measurement
   substrate, but means single-hop-specific interventions need larger
   sample sizes or a tighter envelope (extension to n≥5) to be read
   clearly. Mitigation: explicit recommendation in the F2/F4 charters
   to spike at n=30 stratified by category first, per
   [ADR 0140](./0140-stratified-spike-protocol.md).

### Neutral

1. **Grader and answerer dependency surfaced.** The envelope is
   substrate-conditional on `openai/gpt-4o-mini` answerer at T=0
   max_tokens=2048 and `openai/gpt-4o-mini` judge at max_tokens=16,
   per [PR #88](https://github.com/dave-evolution/uberagent/pull/88)
   and the F1 substrate. Any future change must invalidate-and-rerun.
2. **Run wall-clock time drifts; results do not.** F1 took 4h35m,
   rerun-1 2h50m, rerun-2 3h51m on byte-identical input. Provider-side
   load explains the spread. Operational, not measurement, variance.

## Alternatives considered

### A. Stay with the 49.35% point-estimate gate

Rejected. F3's data shows the rejection rate of equivalent re-runs is
~50% under a 49.35% gate (rerun-1 at 48.79%, rerun-2 at 48.44% — both
would fail). This forces conservative verdicts on nothing-changed
sweeps and would replay T2.1b's mistake on LoCoMo.

### B. Run more samples first (n ≥ 5) before committing to a gate

Tempting. Rejected for now on cost and time grounds: each LoCoMo
rerun is ~$8 / ~3–5h. The n=3 envelope is wide but **monotonic in n**:
F2's planned sweep will extend the envelope when re-graded under the
same substrate (if F2 lands in-envelope it adds to n=4; if F2 lands
out-of-envelope it doesn't count). Subsequent chips tighten σ
automatically. The decision to widen the gate does not require a
tight σ estimate; it requires *any* honest σ estimate, which n=3
provides.

### C. Use the LongMemEval envelope as a proxy

Rejected. LongMemEval's o4-mini overall σ of 0.83pp is 1.8× looser
than LoCoMo's. Cross-benchmark transfer of σ is unsupported: different
corpus structure, different answerer model, different per-category n.
Each benchmark needs its own envelope.

### D. Use only `mean − 1σ` instead of `mean − 2σ`

Rejected. The T2.1b precedent showed that single-sample draws can sit
~1σ below the mean without being regressions. `mean − 2σ` is the
two-tailed 95% threshold (under normality assumptions) and matches
[ADR 0143](./0143-longmemeval-oracle-noise-envelope.md). Symmetry
across the two LoCoMo-and-LongMemEval envelopes is its own value.

## Implementation

1. F2 and F4 chip charters include a "no LoCoMo regression"
   requirement referencing this ADR's table, not the 49.35% point
   estimate.
2. Each new byte-identical LoCoMo sweep (same substrate) appends to
   the envelope. Maintain a running tally in this ADR; recompute mean
   and σ at each append.
3. `scripts/compute_locomo_envelope.py` (added in this chip)
   accepts arbitrary `label=path` graded-JSONL inputs and emits the
   tables above plus pairwise flip matrices. Reusable for envelope
   extension.

## Linked

- [F3 noise-envelope note](../../mind/research/locomo-noise-envelope-2026-05-27.md) — the source chip
- [F1 baseline note](../../mind/research/locomo-baseline-full-2026-05-26.md) — the single-sweep point estimate this ADR widens
- [ADR 0143](./0143-longmemeval-oracle-noise-envelope.md) — LongMemEval analogue; direct methodology twin
- [ADR 0144](./0144-locomo-benchmark-integration.md) — LoCoMo adapter and F1 baseline
- [ADR 0140](./0140-stratified-spike-protocol.md) — stratified spike protocol; relevant for F2/F4 spikes against this envelope
- [ADR 0142](./0142-hybrid-retrieval-for-long-horizon.md) — hybrid retrieval; F2 is its LoCoMo cross-benchmark test
