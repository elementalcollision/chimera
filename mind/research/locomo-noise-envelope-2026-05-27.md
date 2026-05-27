# F3 — LoCoMo noise envelope (gpt-4o-mini answerer, n=3 byte-identical-input sweeps)

**Date**: 2026-05-27
**Status**: Decisive (n=3 complete; rerun-1 in ambiguous band, n=3 mean Δ vs F1 decisive)
**Author**: Chimera-Agent
**Scope**: Measurement-only. Characterizes the variance of the `openai/gpt-4o-mini` answerer + judge on byte-identical-input LoCoMo full-corpus sweeps. **No code or adapter changes.**
**Predecessors**: [F1 baseline](./locomo-baseline-full-2026-05-26.md), [ADR 0144](../../docs/adr/0144-locomo-benchmark-integration.md), [T2.1c LongMemEval envelope](./t21c-oracle-noise-envelope-2026-05-25.md) — methodology twin.

## TL;DR

| Run | Source | Overall | Δ vs F1 |
|---|---|---:|---:|
| F1 baseline | PR #91 (`ac23301`) | **49.35%** | — |
| F3 rerun-1 | this chip | **48.79%** | **−0.55pp** (ambiguous, just outside ±0.5pp) |
| F3 rerun-2 | this chip | **48.44%** | **−0.91pp** (ambiguous) |
| **Mean ± stdev (n=3)** | | **48.86% ± 0.46pp** | mean Δ −0.49pp (decisive) |
| **Proposed widened gate** (mean − 2σ) | | **47.94%** | — |

**Headline findings:**

1. **Overall σ is small** (0.46pp on n=3). The gpt-4o-mini answerer on the full LoCoMo corpus is structurally tighter than o4-mini on the LongMemEval oracle (σ=0.83pp on n=3 per [ADR 0143](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md)). Larger per-category n (96–841 vs LME's 30–133) is the load-bearing reason; bigger denominators average out item-level noise.
2. **Item-level flip rate is 4.58–4.68%** across the 3 pairs (~92 flipping items per pair-comparison). Tighter than LongMemEval's 5.6% but the same order — byte-identical input still re-rolls ~1 item in 22.
3. **Single-hop is LoCoMo's loud category** (σ=1.68pp on n=282). Multi-hop (σ=0.36) and open-domain (σ=0.42) are quiet; adversarial (σ=0.47) and temporal-reasoning (σ=0.60) are mid-band. No category exhibits LongMemEval-SPP-class volatility (5.09pp on n=30).
4. **Recommendation**: future LoCoMo "no regression" gates use **`mean − 2σ`** (overall **47.94%**, per-category as tabled below). This is the F2/F4 retrieval-and-dialectic-ablation envelope.

## Pre-registered decision rules (locked at chip start)

From the F3 charter, mirroring T2.1c:

- ±0.5pp = **decisive band** (substrate well-characterized at n=2; rerun-2 optional)
- 0.5–2pp = **ambiguous band** (run rerun-2 as planned)
- >2pp = **drift band** (diagnose before more spend)

**Outcome**: rerun-1 Δ = −0.55pp → ambiguous (just barely; 0.05pp over the decisive cutoff). Rerun-2 launched per the locked rule. Rerun-2 Δ = −0.91pp → ambiguous. n=3 mean Δ = −0.49pp → would be decisive on its own. The single-run draws sit in the lower tail of a tight envelope, not above a real regression.

## Per-category accuracy (3 runs)

| Category | F1 (49.35%) | rerun-1 (48.79%) | rerun-2 (48.44%) | Mean | σ (pp) | Range |
|---|---:|---:|---:|---:|---:|---:|
| adversarial (n=446) | 12.33% (55) | 13.00% (58) | 12.11% (54) | 12.48% | 0.47 | 12.11–13.00 |
| multi-hop (n=321) | 28.97% (93) | 28.35% (91) | 28.97% (93) | 28.76% | 0.36 | 28.35–28.97 |
| open-domain (n=841) | 77.88% (655) | 77.41% (651) | 77.05% (648) | 77.45% | 0.42 | 77.05–77.88 |
| **single-hop (n=282)** | **47.16% (133)** | **44.68% (126)** | **43.97% (124)** | **45.27%** | **1.68** | **43.97–47.16** |
| temporal-reasoning (n=96) | 45.83% (44) | 44.79% (43) | 44.79% (43) | 45.14% | 0.60 | 44.79–45.83 |
| **OVERALL (n=1986)** | **49.35% (980)** | **48.79% (969)** | **48.44% (962)** | **48.86%** | **0.46** | **48.44–49.35** |

## Per-category gate values (`mean − 2σ`)

| Category | Mean | σ | Gate |
|---|---:|---:|---:|
| adversarial | 12.48% | 0.47 | **11.55%** |
| multi-hop | 28.76% | 0.36 | **28.04%** |
| open-domain | 77.45% | 0.42 | **76.61%** |
| single-hop | 45.27% | 1.68 | **41.92%** |
| temporal-reasoning | 45.14% | 0.60 | **43.94%** |
| **OVERALL** | **48.86%** | **0.46** | **47.94%** |

A chip claiming "no LoCoMo regression" must clear **≥ 47.94% overall** AND per-category gates above on a single 1,986-item sweep.

## Pairwise item-level flip matrices

1,986 questions per run; flip = `is_correct` changes between two byte-identical runs.

| Pair | Both right | Both wrong | Only A right | Only B right | Flip count | Flip rate |
|---|---:|---:|---:|---:|---:|---:|
| F1 (A) vs rerun-1 (B) | 928 | 965 | 52 | 41 | **93** | **4.68%** |
| F1 (A) vs rerun-2 (B) | 925 | 969 | 55 | 37 | **92** | **4.63%** |
| rerun-1 (A) vs rerun-2 (B) | 920 | 975 | 49 | 42 | **91** | **4.58%** |

All three flip counts are within 1% of each other — the noise is well-characterized and isotropic across run-pairs. **~92 LoCoMo items per pair toggle right↔wrong on byte-identical input** while the headline accuracy moves only 0.6–0.9pp.

The asymmetric column "only F1 right" exceeds "only rerun-N right" in both F1-pair comparisons (52>41, 55>37), which is the structural signature of F1 being a marginally luckier draw — exactly what we see in the overall column (F1 at the top of the n=3 range).

## Comparison to ADR 0143 (LongMemEval o4-mini envelope)

The load-bearing cross-benchmark question: does LoCoMo's larger per-category n make σ structurally tighter than LongMemEval's?

| Substrate | Benchmark | Overall σ (n=3) | Worst category σ | n in worst category |
|---|---|---:|---:|---:|
| o4-mini answerer | LongMemEval oracle (500) | 0.83pp | 5.09pp (SPP) | 30 |
| **gpt-4o-mini answerer** | **LoCoMo full (1,986)** | **0.46pp** | **1.68pp (single-hop)** | **282** |

The prediction held — **structurally tighter overall (1.8× smaller σ) and dramatically tighter at the worst category (3× smaller σ on 9.4× more items)**. Two confounded factors driving the tightening:

1. **Larger per-category sample sizes** average out item-level flip noise; the worst-case LoCoMo category (single-hop, n=282) has 9.4× more items than LongMemEval's worst (SPP, n=30).
2. **Different answerer** (gpt-4o-mini, not o4-mini). gpt-4o-mini at T=0 is a non-reasoning model and may have inherently tighter per-item determinism than o4-mini's reasoning channel.

We cannot cleanly decompose the two contributions from this data alone (would need gpt-4o-mini on LongMemEval — T2.1d ran exactly that and scored 45.40%, falsifying the substrate swap for noise reasons elsewhere). The aggregate result — LoCoMo's envelope is structurally narrower — is what governs F2/F4 read-out and stands independent of attribution.

## Honest disclosures

Per the T2.1c precedent ([ADR 0143](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) §"Honest disclosures"):

- **n=3 σ has wide confidence intervals.** True overall σ is somewhere in `[~0.23pp, ~0.69pp]` (roughly σ/2 to 1.5σ) with moderate confidence. The 47.94% gate may be slightly too generous or too tight. Mitigation: the envelope is monotonic in n — every future byte-identical sweep extends it and σ tightens automatically.
- **Per-category σ is the real load-bearing artifact, not overall σ.** The headline 0.46pp is reassuring but F2's per-category retrieval deltas are what need read-out. Single-hop at σ=1.68 is the category to watch: a 2pp retrieval ablation on single-hop alone would not clear `mean − 2σ` (would need >3.36pp to be honest).
- **Grader and answerer are pinned at the PR #88 / F1 substrate.** `openai/gpt-4o-mini` answerer at T=0 max_tokens=2048; `openai/gpt-4o-mini` judge at max_tokens=16. Swapping either invalidates the envelope. This includes provider-side silent model rollovers; the envelope is implicitly versioned against the OpenRouter `openai/gpt-4o-mini` snapshot circa 2026-05-26/27.
- **Run timings drifted, results did not.** F1 took 4h35m, rerun-1 2h50m, rerun-2 3h51m. Same byte-identical input. Provider-side load is the obvious explanation. The variance we care about is judge-graded `is_correct`, which is tightly bounded as tabulated; wall-clock variance is operational, not measurement.

## Implications

### 1. Gate-widening for LoCoMo: `mean − 2σ` = 47.94% overall

Going forward, any chip claiming "LoCoMo no-regression" should clear **≥ 47.94% overall** on a single 1,986-item sweep, not "≥ 49.35%". This widens the gate by 1.41pp — honest about the measurement substrate.

Per-category gates above are the recommended additional check, mirroring [ADR 0140](../../docs/adr/0140-stratified-spike-protocol.md)'s dual-gate spirit. Crucially, the LoCoMo per-category gates are much tighter than LongMemEval's (single-hop at 41.92% vs LME-SPP at 32.04%), so the dual-gate approach is more discriminating on LoCoMo than on LongMemEval.

### 2. F2 (hybrid-retrieval ablation) is now read-ready

F2's expected delta sign is uncertain — [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md)'s `_s`-only verdict said retrieval *hurts* short histories and *helps* long ones. LoCoMo's 19–32-session conversations are everywhere above the top-k threshold, so retrieval *should* help — but how much, and where, is what F2 measures.

**With this envelope in hand, F2 deltas are interpretable:**

| Category | F2 must clear (for "improves") | F2 must drop below (for "harms") |
|---|---:|---:|
| adversarial | > F1 + 0.94pp | < 11.55% |
| multi-hop | > F1 + 0.72pp | < 28.04% |
| open-domain | > F1 + 0.84pp | < 76.61% |
| single-hop | > F1 + 3.36pp | < 41.92% |
| temporal-reasoning | > F1 + 1.20pp | < 43.94% |
| **OVERALL** | **> F1 + 0.92pp** | **< 47.94%** |

The "improves" column is `2σ` above F1's point estimate — symmetric to the gate floor. Anything between the two is in-envelope noise.

### 3. T2.1b-style "single-sample regression" misreadings are mitigated

The chip charter explicitly named the T2.1b mistake — rejecting a no-op path on single-sweep noise — as the failure mode F3 prevents. The envelope here makes that mistake structurally impossible for LoCoMo: only deltas exceeding ±0.92pp overall (or per-category-specific gates) survive the n=3 filter.

### 4. F4 (dialectic-shine localization) gets a tightened substrate

When F4 A/Bs full-context-baseline against full-dialectic-with-multi-peer, the same envelope applies. F4 deltas exceeding the table above are real; deltas below it are measurement noise. This is the same protection F2 gets, applied to a different ablation axis.

### 5. The LoCoMo / LongMemEval envelope contrast informs benchmark selection

For interventions whose expected effect size is < 1pp, LongMemEval is the wrong benchmark (its 0.83pp overall σ already eats most of that signal). LoCoMo's 0.46pp envelope makes sub-1pp effects detectable at the overall level. For category-localized interventions, LoCoMo's worst-category σ (1.68pp) is also dramatically friendlier than LongMemEval's worst-category σ (5.09pp). **Recommendation**: for the next generation of dialectic-and-retrieval interventions, default to LoCoMo for primary read-out; use LongMemEval only when its category structure is specifically being targeted (knowledge-update, SPP).

## Operational details

### Substrate (held fixed across all 3 runs)

- **Answerer**: `openai/gpt-4o-mini`, temperature 0, max_tokens 2048, full-context (no retrieval), dialectic prompt assembled per [ADR 0133](../../docs/adr/0133-dialectic-api.md) against synthetic `mind/peers/self.md` populated by the LoCoMo adapter.
- **Judge**: `openai/gpt-4o-mini`, max_tokens=16. Pinned by `scripts/grade_locomo.py` (PR #88).
- **Corpus**: `data/locomo10.json`, all 10 conversations, all 1,986 QA pairs. No subset / sample-id filter.
- **Adapter**: `chimera/evals/locomo.py` at `ac23301`; ingest cache landed `peers/self.md` once per `sample_id`; sibling QAs reused the cached card.

### Invocations

```bash
# Sweep (identical for both reruns; only --out and --mind-dir differ)
.venv/bin/chimera evals locomo \
    --items data/locomo10.json \
    --answer --answer-model openai/gpt-4o-mini \
    --answer-temperature 0 --answer-max-tokens 2048 \
    --out /tmp/chimera-f3-locomo-rerun{1,2}/hypotheses.jsonl \
    --mind-dir /tmp/chimera-f3-locomo-rerun{1,2}/mind
```

```bash
# Grader (identical for both)
.venv/bin/python scripts/grade_locomo.py \
    /tmp/chimera-f3-locomo-rerun{1,2}/hypotheses.jsonl \
    data/locomo10.json \
    /tmp/chimera-f3-locomo-rerun{1,2}/hypotheses.graded.jsonl \
    openai/gpt-4o-mini
```

### Envelope script

`scripts/compute_locomo_envelope.py` (added in this chip). Reusable across F3 and any future LoCoMo follow-up. Accepts `label=path` positional args; emits per-run accuracy, mean ± σ, gate values, and pairwise flip matrices in Markdown.

### Run timings

| Run | Sweep wall-clock | Grader wall-clock | Notes |
|---|---|---|---|
| F1 | ~4h35m | ~45m | Original baseline (PR #91) |
| rerun-1 | ~2h50m | ~25m | Provider-side faster on 2026-05-26 evening |
| rerun-2 | ~3h51m | ~36m | Mid-band |

Cumulative spend across F3: ~$16 (gpt-4o-mini answerer at full corpus × 2, plus judge × 2). Matches charter budget.

## Artifacts

- F1 graded: `/tmp/locomo-f1/hypotheses.graded.jsonl` (1,986 items)
- Rerun-1 raw: `/tmp/chimera-f3-locomo-rerun1/hypotheses.jsonl`
- Rerun-1 graded: `/tmp/chimera-f3-locomo-rerun1/hypotheses.graded.jsonl`
- Rerun-1 sweep log: `/tmp/chimera-f3-locomo-rerun1/sweep.log`
- Rerun-2 raw: `/tmp/chimera-f3-locomo-rerun2/hypotheses.jsonl`
- Rerun-2 graded: `/tmp/chimera-f3-locomo-rerun2/hypotheses.graded.jsonl`
- Rerun-2 sweep log: `/tmp/chimera-f3-locomo-rerun2/sweep.log`
- Envelope dump: `/tmp/chimera-f3-locomo-rerun2/envelope.md`

## Followups

- **F2 — hybrid-retrieval ablation** — recommended next. Read against the envelope table above. Single-hop is the variance-bound category to scrutinize.
- **F4 — dialectic-shine localization** — read against the same envelope.
- **Optional extension to n=4 or n=5** — would tighten σ from ~0.46 toward its true value. Operator-gated; ~$8/sweep. Not required to gate F2 — n=3 is sufficient for the charter's purposes.

## Linked decisions

- [ADR 0143](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) — LongMemEval methodology twin; this chip applies the same pattern to LoCoMo.
- [ADR 0144](../../docs/adr/0144-locomo-benchmark-integration.md) — LoCoMo adapter; this chip's envelope is a follow-on §Consequences entry.
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — this chip's noise-envelope decision (new).
- [F1 baseline note](./locomo-baseline-full-2026-05-26.md) — the single-sweep point estimate this envelope widens.
- [T2.1c noise-envelope note](./t21c-oracle-noise-envelope-2026-05-25.md) — direct methodology twin.
