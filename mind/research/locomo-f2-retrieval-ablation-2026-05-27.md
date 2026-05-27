# F2 — LoCoMo hybrid-retrieval ablation

**Date**: 2026-05-27
**Status**: PENDING — sweep in progress
**Chip**: F2 — hybrid-retrieval ablation against F1 LoCoMo baseline
**Predecessors**:
- [F1 baseline](./locomo-baseline-full-2026-05-26.md) — 49.35% overall, 1,986-item ground truth
- [F3 noise envelope](./locomo-noise-envelope-2026-05-27.md) — σ=0.46pp overall; locked gates from ADR 0145
- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid-retrieval decision (+56.67pp on LME `_s`)
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — gate authority

## TL;DR

<!-- FILL IN AFTER GRADING -->
**VERDICT**: PENDING

## Side-by-side F1 vs F2 per-category table

<!-- FILL IN AFTER GRADING -->

| Category | F1 | F2 | Δ |
|---|---:|---:|---:|
| adversarial (n=446) | 12.33% (55) | — | — |
| multi-hop (n=321) | 28.97% (93) | — | — |
| open-domain (n=841) | 77.88% (655) | — | — |
| single-hop (n=282) | 47.16% (133) | — | — |
| temporal-reasoning (n=96) | 45.83% (44) | — | — |
| **OVERALL (n=1986)** | **49.35% (980)** | **—** | **—** |

## Per-category gate clearance

Pre-registered gates (LOCKED from ADR 0145 — no recomputation):

| Category | F1 | Improves if | Harms if | F2 | Improves? | Harms? |
|---|---:|---:|---:|---:|:---:|:---:|
| adversarial | 12.33% | > 13.27% | < 11.55% | — | — | — |
| multi-hop | 28.97% | > 29.69% | < 28.04% | — | — | — |
| open-domain | 77.88% | > 78.72% | < 76.61% | — | — | — |
| single-hop | 47.16% | > 50.52% | < 41.92% | — | — | — |
| temporal-reasoning | 45.83% | > 47.03% | < 43.94% | — | — | — |
| **OVERALL** | **49.35%** | **> 50.27%** | **< 47.94%** | **—** | **—** | **—** |

## Locked-outcome verdict

<!-- FILL IN AFTER GRADING -->

Outcome bands (pick exactly one):
- **HELPS**: overall > F1+0.92pp AND ≥2/5 categories clear "improves" AND no category clears "harms".
- **HURTS**: overall < 47.94% OR any category clears "harms".
- **IN-ENVELOPE NOISE**: overall delta inside ±2σ AND no category clears either bar.
- **MIXED**: some help, others hurt.

**VERDICT**: PENDING

## Item-level flip analysis

<!-- FILL IN AFTER compute_locomo_envelope.py -->

F1→F2 flip distribution:
- Category distribution of flips: PENDING
- Oscillation vs F3 envelope σ: overall σ=0.46pp, single-hop σ=1.68pp (the loud category)
- ~92 items flip per pair on byte-identical input; F2 flag changes are additional structure beyond that noise floor

## Cross-benchmark synthesis

ADR 0142's `_s` result: **+56.67pp** (10.00% → 66.67%) on LongMemEval `_s` long-horizon (n=30 stratified, BM25-only in practice). The `_s` variant has ~48 sessions/~493 turns per item — the retrieval layer's purpose is to compress a 500 KB context to the top-k=8 relevant sessions.

LoCoMo conversations are 19–32 sessions. The F1 substrate uses full context. Hybrid-retrieval top-k=8 on LoCoMo:
- Conversations with ≤8 sessions pass through unchanged (auto no-op path per ADR 0142 §Decision)
- Conversations with >8 sessions get compressed to the 8 most relevant sessions per BM25+dense RRF

**Substrate confound**: The LongMemEval `_s` benchmark ran with `o4-mini` as answerer (reasoning model); F2 uses `gpt-4o-mini` (non-reasoning). These are not directly comparable. The +56.67pp `_s` result is a different substrate:
1. Different answerer model class (reasoning vs. non-reasoning)
2. Different benchmark (LongMemEval vs. LoCoMo)
3. Different baseline degradation pattern (`_s` at 10% vs. LoCoMo F1 at 49.35%)

The LongMemEval `_s` result demonstrated that retrieval can rescue a collapsed context window. LoCoMo F1 is not collapsed — 49.35% on full context is competitive. The question is whether retrieval compression _adds_ signal or _loses_ signal when the baseline is already healthy.

## Honest disclosures

1. **Single-sweep caveat**: F2 is one sweep. The F3 envelope (σ=0.46pp overall, σ=1.68pp single-hop) bounds interpretation. Deltas inside ±0.92pp overall and inside per-category 2σ bands are consistent with measurement noise.

2. **Substrate confound**: F2 uses `gpt-4o-mini` (same as F1/F3). The LongMemEval `_s` baseline used `o4-mini`. Cross-benchmark comparison of the +56.67pp `_s` win against F2's LoCoMo delta is confounded by model class. The LoCoMo F2 result is the cleaner signal for gpt-4o-mini's retrieval sensitivity.

3. **Conservative-gate worst-case**: The "improves" column requires clearing F1 + 2σ — this is symmetric to the harm gate. Any result between the two thresholds is definitionally in-envelope noise and cannot be called a win or a loss at the n=1 sweep level.

4. **BM25+dense or BM25-only?** ADR 0142 §"Methodology caveat" documents that both LongMemEval sweeps ran BM25-only (Voyage rate-limited). If Ollama dense embedder is unavailable or slow, LoCoMo F2 degrades to BM25-only as well. Check sweep logs for `degraded to BM25-only` messages.

## Operational details

### Substrate

- **Answerer**: `openai/gpt-4o-mini`, temperature 0, max_tokens 2048
- **Flags**: `--hybrid-retrieval --retrieval-top-k 8`
- **Judge**: `openai/gpt-4o-mini`, max_tokens=16 (same as F1/F3)
- **Corpus**: `/tmp/locomo/locomo10.json`, all 1,986 QA pairs
- **Grader**: `scripts/grade_locomo.py` default (no judge override)

### Invocation

```bash
chimera evals locomo \
  --items /tmp/locomo/locomo10.json \
  --answer --answer-model openai/gpt-4o-mini \
  --answer-temperature 0 --answer-max-tokens 2048 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-f2-locomo/results.jsonl \
  --mind-dir /tmp/chimera-f2-locomo/mind
```

### Artifacts

- Raw JSONL: `/tmp/chimera-f2-locomo/results.jsonl`
- Graded JSONL: `/tmp/chimera-f2-locomo/results.graded.jsonl`
- Sweep log: `/tmp/chimera-f2-locomo/sweep.log`

## Linked decisions

- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid-retrieval decision (cross-benchmark anchor target)
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — gate authority for this chip
- [F1 baseline note](./locomo-baseline-full-2026-05-26.md) — F1 point estimate
- [F3 noise envelope note](./locomo-noise-envelope-2026-05-27.md) — σ values and gate derivation
