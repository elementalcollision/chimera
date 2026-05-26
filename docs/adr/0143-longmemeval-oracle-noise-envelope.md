# ADR 0143 — LongMemEval oracle noise envelope: future "no regression" gates use `mean − 2σ`

**Status**: Accepted (2026-05-25). Records the noise-envelope characterization from T2.1c.

## Context

The post-T1.5 LongMemEval oracle baseline of **90.80% / 500 items**
(commit `14192658`, see [longmemeval-baseline-post-t1.5-2026-05-25.md](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md))
was a **single-sweep point estimate**. Every "no regression" gate that
followed it — including [ADR 0142](./0142-hybrid-retrieval-for-long-horizon.md)'s
oracle gate — implicitly treated 90.80% as the true population mean.

T2.1b (PR #86) ran a second sweep under what was diagnosed post-hoc as
a **byte-identical no-op** code path (every oracle item took the
`len(history) ≤ top_k` branch in the hybrid-retrieval session selector,
making the dialectic prompt identical to baseline). It scored 89.20%
overall, −1.60pp from the point estimate, and was failed by the
pre-registered gate even though no observable code-path difference
existed. The failure-mode diagnostic concluded the drop was answerer
stochasticity, not a retrieval defect.

T2.1c (this ADR's source chip) ran a third byte-identical-input sweep
on the same current main (`1f63335`). Headline:

| Run | Overall | KU | SPP |
|---|---:|---:|---:|
| post-T1.5 baseline | 90.80% | 96.15% | 46.67% |
| T2.1b | 89.20% | 88.46% | 43.33% |
| T2.1c rerun 1 | 90.40% | 96.15% | 36.67% |
| **mean (n=3)** | **90.13%** | **93.59%** | **42.22%** |
| **stdev (n=3)** | **0.83pp** | **4.44pp** | **5.09pp** |

Detail and per-pair flip matrices in [T2.1c noise-envelope note](../../mind/research/t21c-oracle-noise-envelope-2026-05-25.md).

Two structural findings:

1. **Aggregate variance is small but non-trivial.** Overall σ = 0.83pp
   on three samples; range 1.60pp across byte-identical inputs.
2. **Category-localized variance is large and bimodal.**
   Single-session-preference σ = 5.09pp on n=30, knowledge-update σ =
   4.44pp on n=78. Other categories σ ≤ 2.2pp. Roughly 5.6% of items
   flip identity between any two byte-identical runs even when overall
   accuracy is stable.

A point-estimate gate at 90.80% therefore rejects ~half of equivalent
re-runs of the same configuration. This is the wrong failure mode: it
forces conservative chip verdicts (T2.1b → `_s`-only) on what may be
unbiased measurement noise.

## Decision

**The "no regression" gate for future LongMemEval oracle sweeps is
`mean − 2σ` over the envelope of byte-identical-input reruns, not the
single-sample point estimate.**

### Current envelope (as of 2026-05-25, n=3)

| Scope | Mean | σ | Gate (`mean − 2σ`) |
|---|---:|---:|---:|
| **Overall** | **90.13%** | **0.83pp** | **88.47%** |
| knowledge-update | 93.59% | 4.44pp | 84.71% |
| multi-session | 89.22% | 1.15pp | 86.92% |
| single-session-assistant | 98.81% | 1.03pp | 96.75% |
| **single-session-preference** | **42.22%** | **5.09pp** | **32.04%** |
| single-session-user | 99.05% | 0.82pp | 97.41% |
| temporal-reasoning | 91.48% | 2.17pp | 87.14% |

A chip claiming "oracle no-regression" must clear **≥ 88.47% overall**
on a single 500-item sweep. Per-category clearance against the
per-category gates is recommended (mirrors [ADR 0140](./0140-stratified-spike-protocol.md)'s
dual-gate spirit) but not required at this ADR's level — that's a
follow-up decision for ADR 0140 once it's promoted from Proposed.

### Envelope update policy

- Each new byte-identical oracle sweep extends the envelope. Recompute
  mean and σ.
- The envelope is **monotonic in n**: σ estimates from n=3 are wide
  confidence intervals. Once n ≥ 5, σ stabilizes and the gate
  tightens automatically.
- When the answerer or grader configuration changes (different
  `--answer-model`, different judge model, different `max_tokens`),
  the envelope is **invalidated** and must be re-characterized.

## Consequences

### Positive

1. **Failure-mode honesty.** Chips no longer fail on −1.60pp draws that
   are within measurement noise. T2.1b's "Accepted (`_s`-only)" verdict
   becomes defensibly conservative rather than substantively required.
2. **Stratified spike protocol ([ADR 0140](./0140-stratified-spike-protocol.md))
   gets quantitative backing.** SPP σ = 5.09pp at n=30 confirms n=30
   spikes have ±5pp noise on the noisiest category — which dwarfs most
   intervention effect sizes. ADR 0140's stratified-and-corpus dual-gate
   approach is now empirically justified, not just heuristic.
3. **T2.1d (deterministic answerer pivot) becomes warranted.** The 5.6%
   item-flip rate on byte-identical input is the irreducible noise
   floor of the o4-mini answerer. A temperature=0 / seed-locked
   alternative (or fallback to gpt-4o-mini as answerer for substrate
   sweeps) is the leverage point for tightening the envelope further.
   **Empirical update (2026-05-26)**: T2.1d's first sweep with
   `openai/gpt-4o-mini --answer-temperature 0` scored **45.40%
   overall**, 43pp below this ADR's lower-gate. The fallback to
   gpt-4o-mini-as-answerer is **falsified at the sanity floor** — the
   model-strength differential dominates the sampling-temperature
   differential by orders of magnitude on this benchmark. See
   [T2.1d falsification note](../../mind/research/t21d-deterministic-answerer-envelope-2026-05-26.md)
   for the per-category collapse table and the structural reading.
   The envelope-tightening leverage point exists in principle but is
   not accessible via this answerer choice; the o4-mini envelope
   stands.

### Negative

1. **n=3 σ is wide.** True σ is somewhere in `[0.5pp, 1.5pp]` with
   moderate confidence; the gate at 88.47% may be slightly too generous
   (or slightly too tight). Mitigation: the envelope is monotonic in n
   and will tighten as samples accumulate.
2. **Past chip verdicts retain their original status.** This ADR does
   not retroactively flip ADR 0142 from "Accepted (`_s`-only)" to
   "Accepted (full)"; doing so requires a separate operator decision
   with its own ADR amendment, and is explicitly out of scope here.
3. **Per-category gate floors are very loose** (SPP at 32.04%, KU at
   84.71%). This is honest about the measurement substrate, but it
   means category-localized regressions of up to 12pp could pass.
   Mitigation: ADR 0140's stratified spike + corpus-promotion criterion
   catches localized regressions before they reach the corpus gate.

### Neutral

1. **Grader judge-model dependency surfaced.** `grade.py` defaults to
   `openai/o4-mini` as the judge, but the baseline and T2.1b both used
   `openai/gpt-4o-mini`. The o4-mini judge returns empty content under
   the `max_tokens=16` budget and yields 0% across the board. The
   envelope above is grader-conditional on `openai/gpt-4o-mini`.
   Follow-up: update `grade.py`'s default judge. Not in scope here.

## Alternatives considered

### A. Stay with the 90.80% point-estimate gate

Rejected. T2.1c's data shows the rejection rate of equivalent re-runs
is ~50% under a 90.80% gate. This forces conservative verdicts on
nothing-changed sweeps and would have failed rerun 1 (90.40%, no
hybrid-retrieval flag set, current main).

### B. Run more samples first (n ≥ 5) before committing to a gate

Tempting. Rejected for now on cost/time grounds: each rerun is ~$2 /
~55 min. The n=3 envelope is wide but **monotonic in n**: subsequent
chips can extend the envelope without invalidating it, and the gate
tightens automatically as σ stabilizes. The decision to widen the gate
does not require a tight σ estimate; it requires *any* honest σ
estimate, which n=3 provides.

### C. Switch to a deterministic answerer (T2.1d) first, then re-gate

This is the right long-term move (and is recommended as the next chip
in the T2.1c note), but it should not block the immediate gate widening.
A deterministic answerer would *re-baseline* the envelope, not
substitute for it: even temperature=0 reasoning models have residual
non-determinism (provider-side batching, kernel choice). T2.1d will
produce a new, tighter envelope; this ADR's policy is what governs the
*current* answerer.

**Empirical update (2026-05-26)**: T2.1d was chartered and ran one
sweep at `openai/gpt-4o-mini --answer-temperature 0`. Result: **45.40%
overall** vs this ADR's 88.47% gate. The substrate switch is rejected
at the sanity floor and the alternative is **closed, not pending**.
The failure mode was not what this ADR anticipated (residual T=0
non-determinism); it was a model-strength ceiling — gpt-4o-mini lacks
the long-context reasoning capability that o4-mini contributes,
collapsing the multi-session category from 89.22% to 22.56%. The
o4-mini envelope remains the operative noise model. The next
envelope-tightening leverage point would be either a stronger T=0
answerer (`openai/gpt-4.1-mini` or similar) or provider-side `seed`
pinning on o4-mini itself — both recorded as candidate next chips in
the [T2.1d note](../../mind/research/t21d-deterministic-answerer-envelope-2026-05-26.md),
neither currently chartered.

## Implementation

1. Update [longmemeval-baseline-post-t1.5-2026-05-25.md](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md)
   to cross-reference this ADR (deferred; ADR 0136 cross-reference is
   sufficient for now).
2. Future chip charters that include a "no regression" requirement
   reference this ADR and the envelope table above, not the 90.80%
   point estimate.
3. Each new byte-identical oracle sweep (no `--hybrid-retrieval` flag,
   default `hybrid_retrieval=False`) appends to the envelope. Maintain
   a running tally in this ADR; recompute mean and σ at each append.

## Linked

- [T2.1c noise-envelope note](../../mind/research/t21c-oracle-noise-envelope-2026-05-25.md) — the source chip
- [T2.1b oracle no-regression note](../../mind/research/t21b-oracle-no-regression-2026-05-25.md) — the chip that motivated this characterization
- [Post-T1.5 baseline note](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md) — the single-sweep point estimate this ADR widens
- [ADR 0140](./0140-stratified-spike-protocol.md) — stratified spike protocol; gets quantitative backing from this envelope
- [ADR 0142](./0142-hybrid-retrieval-for-long-horizon.md) — hybrid retrieval; verdict not modified here, but envelope contextualizes it
- [T2.1d falsification note](../../mind/research/t21d-deterministic-answerer-envelope-2026-05-26.md) — empirically closes §Alternatives.C and updates §Consequences.Positive.3
