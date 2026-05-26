# T2.1d — Deterministic-answerer envelope: falsification

**Date**: 2026-05-26
**Chip**: T2.1d (deterministic-answerer pivot)
**Verdict**: **Rejected — substrate switch falsified by sweep 1**
**Linked ADR**: [0143 — LongMemEval oracle noise envelope](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) (§Alternatives C, §Consequences.Positive.3)

## TL;DR

[ADR 0143](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) §Consequences anticipated T2.1d as the leverage point for tightening the o4-mini noise envelope (mean 90.13%, σ 0.83pp). The pre-registered hypothesis: a temperature-pinnable, non-reasoning answerer (`openai/gpt-4o-mini` at `T=0`) would shrink σ enough to detect smaller interventions.

**Sweep 1 falsified the substrate at the very first gate.** Headline:

| Substrate (oracle 500-item) | Mean overall | vs ADR 0143 lower-gate (88.47%) |
|---|---:|---:|
| o4-mini (ADR 0143 envelope, n=3) | **90.13%** | — |
| **gpt-4o-mini T=0 (T2.1d sweep 1, n=1)** | **45.40%** | **−43.07pp** |

Per the chip's pre-registered fallback rule ("if gpt-4o-mini's mean is below 88.47pp, the substrate switch is rejected"), the result is decisive at n=1. Reruns 2 and 3 were skipped with operator authorization: no σ characterization on n=3 can rescue a 43pp mean gap, and burning ~$4 / ~2.5 hr to confirm "still catastrophically below floor" would be performative.

The chip charter explicitly framed this outcome as shippable ("Either outcome is shippable. The chip is **not** required to 'win'; it's required to measure.").

## Headline result

### Sweep 1 — `openai/gpt-4o-mini --answer-temperature 0`

- **Branch**: `chip/t21d-deterministic-answerer` (head `4083189` + plumbing commit)
- **Started**: 2026-05-26, completed ~75 min wall-clock
- **Items**: 500/500 graded (no failures), category distribution matches oracle
- **Grader**: `openai/gpt-4o-mini` (PR #88 pin, unchanged from ADR 0143 substrate)
- **Raw**: `/tmp/chimera-t21d-deterministic-1/results.jsonl`
- **Graded**: `/tmp/chimera-t21d-deterministic-1/results.graded.jsonl`
- **Autosave**: `mind/evals/longmemeval-20260526T141417Z.jsonl`

### Per-category gap vs o4-mini envelope mean

| Category | gpt-4o-mini T=0 (n=1) | o4-mini mean (n=3, ADR 0143) | Δ | gpt-4o-mini vs per-category gate |
|---|---:|---:|---:|:---|
| single-session-assistant | 92.86% (52/56) | 98.81% | −5.95pp | below 96.75% gate |
| single-session-user | 74.29% (52/70) | 99.05% | −24.76pp | below 97.41% gate |
| knowledge-update | 47.44% (37/78) | 93.59% | **−46.15pp** | below 84.71% gate |
| temporal-reasoning | 39.10% (52/133) | 91.48% | **−52.38pp** | below 87.14% gate |
| multi-session | 22.56% (30/133) | 89.22% | **−66.66pp** | below 86.92% gate |
| single-session-preference | 13.33% (4/30) | 42.22% | −28.89pp | below 32.04% gate (only one near-pass) |

**Every category fails its per-category gate.** Overall fails the 88.47% overall gate by 43pp.

## Structural reading of the failure

The collapse is **monotonic in context complexity**, which is exactly the signature of a model-strength ceiling rather than a plumbing defect:

1. **Single-session-assistant** (short context, no cross-turn reasoning) holds near parity at 92.86%. The answerer pipeline, prompt assembly, and provider plumbing are intact. This is the negative control that confirms the failure is not in our code.
2. **Single-session-user** (slightly longer single-session context) loses 25pp.
3. **Knowledge-update / temporal-reasoning** (multi-turn within a session, with temporal grounding) lose 46-52pp.
4. **Multi-session** (cross-session reasoning over the full oracle history) collapses to 22.56%, a 67pp gap. This is the regime where o4-mini's reasoning channel does the most work, and where gpt-4o-mini has the least to offer.
5. **Single-session-preference** is the one category where the gap is *smaller* than expected (only −29pp) — but only because the o4-mini envelope is itself depressed there (mean 42.22%, σ 5.09pp). Both models struggle with implicit preference; this is the [PR #75 / Tier-2B](../research/t21c-oracle-noise-envelope-2026-05-25.md) regime that was already known to be hard.

**Interpretation**: T=0 was the wrong knob. The variance in the o4-mini envelope (σ=0.83pp overall, 5.09pp on SPP) is dominated by reasoning-channel stochasticity that swapping to a non-reasoning model does not eliminate — it just trades the noise for a catastrophic mean collapse. The "temperature is the floor" hypothesis was specifically called out in [ADR 0143 §Alternatives.C](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md) ("even temperature=0 reasoning models have residual non-determinism") but underweighted the prior that the *model strength* differential dominates the *sampling temperature* differential by orders of magnitude on this benchmark.

## What this changes / what it does not

### Changes

- **ADR 0143 §Consequences.Positive.3 is empirically updated**: the "T2.1d (deterministic answerer pivot) becomes warranted" claim is now followed by the falsification record. The leverage point exists in principle but is not accessible via this answerer choice.
- **ADR 0143 §Alternatives.C** ("Switch to a deterministic answerer (T2.1d) first, then re-gate") is updated with the empirical finding. The alternative is closed, not pending.
- **The o4-mini envelope stands as the operative noise model.** ADR 0143's `mean − 2σ = 88.47%` overall gate remains the "no regression" threshold for future LongMemEval oracle sweeps until a stronger answerer alternative is identified.

### Does not change

- ADR 0142's `_s`-only hybrid-retrieval verdict — T2.1d's substrate question is orthogonal to retrieval.
- The grader (`scripts/grade_longmemeval.py`, PR #88-pinned to `gpt-4o-mini`). Envelope characterization depends on grader stability; the grader was held fixed across all three reference baselines and the T2.1d sweep.
- The post-T1.5 baseline (`14192658`, 90.80%) as the historical single-sweep point estimate.

## What an envelope-tightening pursuit would look like (next time)

Pre-registering what *would* be tried before chartering T2.1e, if a future operator wanted to revisit envelope tightening:

1. **Stronger non-reasoning answerers**. The chip considered `openai/gpt-4.1-mini` at the model-choice gate but the pre-registered choice was `gpt-4o-mini`. A stronger T=0 model might both clear the sanity floor *and* tighten σ — the open question is whether T=0 plus a stronger model has lower σ than o4-mini's default. This is the natural T2.1e if anyone wants to pay $6 to find out.
2. **Provider-seed control**. OpenRouter exposes a `seed` parameter on some upstream providers. Pinning both `temperature=0` and `seed` would isolate the irreducible provider-side non-determinism (batching, kernel choice) called out in [ADR 0143 §Alternatives.C](../../docs/adr/0143-longmemeval-oracle-noise-envelope.md). Worth a `_s`-stratified spike before committing oracle-budget to it.
3. **Larger n on the existing o4-mini substrate**. σ at n=3 has wide CIs (`[0.5pp, 1.5pp]` per ADR 0143 §Negative.1). A fourth o4-mini sweep is ~$2 and would tighten the gate by ~0.1-0.3pp without changing substrate. Cheapest envelope improvement available; ADR 0143's update policy already permits it.

None of these are chartered. They are recorded here so the next operator does not re-derive them.

## Operational details

### Sweep 1 invocation

```bash
PYTHONPATH=/Users/dave/uberagent-t21d \
  /Users/dave/uberagent/.venv/bin/python -c \
    "import sys; sys.path.insert(0,'/Users/dave/uberagent-t21d'); from chimera.cli import main; sys.exit(main())" \
    evals longmemeval \
    --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
    --answer --answer-model openai/gpt-4o-mini --answer-temperature 0 --answer-max-tokens 2048
```

Notes:

- The `PYTHONPATH`/`python -c` indirection was needed because the parent `.venv`'s installed `chimera` entry-point shim resolves to `/Users/dave/uberagent` (main), not the worktree. Future T2.1*-class chips should either (a) install `chimera` into a worktree-local venv, or (b) add a `__main__.py` to `chimera/` so `python -m chimera` works for ad-hoc CLI override. Filed as a housekeeping note, not in scope here.
- `--answer-temperature 0` is the new flag landed in this chip's plumbing commit (see PR diff).
- No `--hybrid-retrieval` flag — oracle path, identical retrieval configuration to ADR 0143's envelope baselines.

### Grading

```bash
python scripts/grade_longmemeval.py \
    /tmp/chimera-t21d-deterministic-1/results.jsonl \
    /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
    /tmp/chimera-t21d-deterministic-1/results.graded.jsonl
```

Default judge `openai/gpt-4o-mini` (PR #88). No grader pitfalls — the footgun ADR 0143 §Consequences.Neutral.1 flagged was closed by PR #88.

### Cost & time

- Sweep 1: ~75 min wall-clock, ~$1.50 estimated spend (within chip budget of $1-2/run).
- Reruns 2&3: not run. ~$3-4 / ~2.5 hr saved.
- Grading: ~2 min, included in sweep total.

## Artifacts

- Sweep 1 raw: `/tmp/chimera-t21d-deterministic-1/results.jsonl`
- Sweep 1 graded: `/tmp/chimera-t21d-deterministic-1/results.graded.jsonl`
- Sweep autosave (worktree): `mind/evals/longmemeval-20260526T141417Z.jsonl`
- Sweep log: `/tmp/chimera-t21d-deterministic-1/sweep.log`
- Grade log: `/tmp/chimera-t21d-deterministic-1/grade.log`

## Followups

- **None active.** ADR 0143 stands; T2.1e (stronger non-reasoning answerer) and T2.1f (provider-seed pinning) are recorded above but not chartered.
- The CLI plumbing (`--answer-temperature` flag) is preserved in main and remains available for any future envelope-tightening experiment without re-doing the adapter work.
