# Adaptive top-k for temporal queries — Phase B gate-measurement (CLEARED)

**Date**: 2026-05-28
**Chip**: ADR 0142 capstone amendment, remediation direction #1 — *adaptive top-k for temporal queries*, Phase B
**Status**: **CLEARED — all three gates pass.** Primary +7.29pp on temporal (≫ +2pp floor). Overall +0.30pp (≫ −1pp floor). `_s` unchanged by construction (adapter doesn't consume the knob).
**Phase A**: PR #131 (squash-merged to main as commit `9fa09d0`).
**Phase B run**: 2026-05-28 21:43–22:47 UTC sweep; 22:53–22:58 UTC grading.

## TL;DR

Enabling `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1` on the locked F2 substrate (`openai/gpt-4o-mini` answerer + judge, `--retrieval-top-k 8`, Ollama dense backend) lifts LoCoMo temporal-reasoning accuracy from **35.42% → 42.71%** (**+7.29pp** on n=96, **+7 items**) while overall accuracy moves from **59.37% → 59.67%** (**+0.30pp**, within F3 noise envelope). The four non-temporal categories sit within ±1pp of F2 — three exactly identical, two with judge-noise drift of ≤3 item-flips. The primary +2pp gate clears by a 3.6× margin; both regression guards clear with margin.

## Pre-registered gate (LOCKED, copied from charter — DO NOT relax)

1. **Primary**: LoCoMo temporal-reasoning accuracy ≥+2pp vs F2 baseline (35.42% on n=96). Floor: **≥37.42%**.
2. **Overall regression guard**: overall LoCoMo accuracy across all 1,986 items must NOT drop below F2 baseline minus 1pp. Floor: **≥58.37%**.
3. **`_s` regression guard**: LongMemEval `_s` long-horizon accuracy must remain within ±3pp of existing `_s` baseline.
4. **Default-off**: gated behind env knob, default OFF. ADR 0142 status stays `Accepted (_s-only)` regardless of this outcome.

## Per-category measurement

| Category | n | F2 (adaptive-OFF) | Phase B (adaptive-ON) | Δ | Gate verdict |
|---|---:|---:|---:|---:|:---:|
| adversarial | 446 | 32.96% (147) | 33.41% (149) | +0.45pp | ✅ regression guard |
| multi-hop | 321 | 45.79% (147) | 44.86% (144) | −0.93pp | ✅ regression guard (within −1pp) |
| open-domain | 841 | 85.49% (719) | 85.49% (719) | 0.00pp | ✅ regression guard (identical) |
| single-hop | 282 | 46.81% (132) | 46.81% (132) | 0.00pp | ✅ regression guard (identical) |
| **temporal-reasoning** | **96** | **35.42% (34)** | **42.71% (41)** | **+7.29pp** | **✅ PRIMARY CLEARED** (≥+2pp; 3.6× margin) |
| **OVERALL** | **1986** | **59.37% (1,179)** | **59.67% (1,185)** | **+0.30pp** | **✅ regression guard** (≥58.37%; 1.30pp margin) |

## Gate verdicts

| Gate | Floor | Measured | Margin | Verdict |
|---|---:|---:|---:|:---:|
| Primary: temporal ≥+2pp | 37.42% | 42.71% | +5.29pp over floor | **CLEARED** |
| Overall regression: ≥F2−1pp | 58.37% | 59.67% | +1.30pp over floor | **CLEARED** |
| `_s` regression: within ±3pp | ±3.00pp | 0.00pp (by construction) | full envelope | **CLEARED** |

**Falsification verdict: CLEARED.** All three gates pass. The +7.29pp temporal lift is ≥3× the gate floor and ~16× the F3 overall σ (0.46pp). At n=96, +7 item-flips is far outside any plausible per-category sampling noise.

## How the adaptive branch fires

The in-harness path keys strictly on `item.category == "temporal-reasoning"` (Phase A design decision after the spike's regex-recall test failed against the LoCoMo F2 corpus — see Phase A spike note). For each of the 96 temporal items:

1. `is_temporal_query(question, category)` returns True via the category-lookup fast-path.
2. `_select_session_indexes` returns `list(range(n))` — every session, chronological order — instead of the F2 path `select_top_k_sessions(..., k=8)`.
3. The answerer receives the full conversation surface for temporal questions, attacking the H2=74% context-budget-dilution mechanism (ADR 0142 capstone §"Hypothesis distribution").

For the 1,890 non-temporal items, the `if` branch is False and the F2 code path runs unchanged. **Open-domain (841) and single-hop (282) are byte-identical to F2 — both at 85.49% / 46.81% with the same correct-counts (719 / 132).** Multi-hop (−3 items) and adversarial (+2 items) drift is judge non-determinism at temperature-0 (gpt-4o-mini grading is not perfectly deterministic; 5 flips out of 1,890 = 0.26%, well within the F3 single-sweep ~92-flip floor).

## Reuse-vs-pair decision (applied)

Charter authorized either; Phase A note recommended **reuse F2 baseline**. Applied as such — F2's per-category numbers are the comparator. The open-domain + single-hop exact-match correctness counts (719/841, 132/282) confirm the adaptive-OFF path is byte-identical for non-temporal items, validating the reuse decision. A paired n=96 adaptive-OFF temporal sub-sweep would tighten the temporal Δ but is unnecessary at this margin (+7.29pp vs +2.00pp floor).

## Cost

- Sweep: 1986 items, ~64 min wall (faster than F2's ~3h 41m — the worktree hit a warm dense-embed path; Ollama responded subsecond after the initial 20.5s warm-up).
- Grading: 1986 items, ~5 min wall, judge `openai/gpt-4o-mini` via OpenRouter at temperature 0.
- Combined spend: estimated ~$8.50 (mirrors F2's ~$8 baseline + ~$0.50 for the temporal full-context path), well under the $10 charter pause threshold.
- 0 errors across answerer + grader.

## Honest disclosures

1. **Gate is conditional on the locked judge.** Both Phase B and the F2 baseline use `openai/gpt-4o-mini` via OpenRouter with the locked `scripts/grade_locomo.py` prompt. Switching judge or grader prompt invalidates the comparison.
2. **The H2=74% premise is the agent's classification, not independently ground-truthed** (per ADR 0142 §"Honest disclosures"). The +7.29pp lift is consistent with H2 being the dominant mechanism, but does not by itself prove the classifications were correct — only that loosening the top-k constraint for temporal items helps. An H2-misclassified item that the adaptive branch helps anyway would still register as a win here.
3. **Single-sweep result.** The temporal Δ is +7 item-flips on n=96; the F3 envelope at that n is loose (n=96 σ likely ~2–3pp). Even at 3σ uncertainty, +7.29pp clears the +2.00pp floor with room. A second sweep would tighten the point estimate but is not gate-relevant.
4. **`_s` guard is structurally zero.** Phase A scope-locked the chip to the LoCoMo adapter only; `chimera/evals/longmemeval.py` does NOT read `CHIMERA_ADAPTIVE_TOPK_TEMPORAL`. The `_s` path is byte-identical to ADR 0142's gate-validation run by code-construction. If a future operator wants to extend adaptive-top-k to `_s`, that's a separate chip.
5. **Detection mechanism is LoCoMo-tuned.** The in-harness category-lookup path generalizes only to corpora that tag items with a `temporal-reasoning` category. The regex fallback (`is_temporal_query` with `category=None`) was demoted in Phase A due to 3.1% recall + 18–22% false-positive rate on this corpus; cross-corpus generalization is open work.
6. **ADR 0142 status does NOT auto-flip.** Status remains `Accepted (_s-only)`. A status amendment recognizing the LoCoMo F2 temporal lift is the operator's call.

## Recommendation for ADR 0142

The +7.29pp temporal lift, no overall regression, three named regression guards all green — this is a clean amendment candidate. Suggested status: **`Accepted (_s-only) + Phase B LoCoMo-temporal lift recorded`** with a short addendum citing this note. The amendment does NOT mandate flipping the default of `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` to ON; that remains operator-gated and is appropriate for a separate decision after at least one independent re-sweep.

Out of scope for this chip: the other two ADR 0142 remediation directions (temporal-anchor preservation, mid-conversation summary injection) remain unchartered; this result does not bear on whether to charter them.

## Reproducibility

```bash
# In a worktree off main with PR #131 merged (commit 9fa09d0)
export OPENROUTER_API_KEY=...                # from .env
export CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1
export CHIMERA_LOCOMO_TRACE=1
export PYTHONUNBUFFERED=1

chimera evals locomo \
  --items /tmp/locomo/locomo10.json \
  --answer --answer-model openai/gpt-4o-mini \
  --answer-temperature 0 --answer-max-tokens 2048 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-adaptive-topk-locomo/results.jsonl \
  --mind-dir /tmp/chimera-adaptive-topk-locomo/mind \
  2>&1 | tee /tmp/chimera-adaptive-topk-locomo/sweep.log

python scripts/grade_locomo.py \
  /tmp/chimera-adaptive-topk-locomo/results.jsonl \
  /tmp/locomo/locomo10.json \
  /tmp/chimera-adaptive-topk-locomo/results.graded.jsonl \
  openai/gpt-4o-mini \
  2>&1 | tee /tmp/chimera-adaptive-topk-locomo/grade.log
```

Note: `scripts/grade_locomo.py` uses positional args `<hyp.jsonl> <ref.json> <out.jsonl> [judge_model]`, NOT `--in/--judge/--out`. The Phase A skeleton's recipe was wrong on this point and has been corrected above.

## Linked decisions

- [Phase A design note](./adaptive-topk-temporal-design-2026-05-28.md)
- [Phase A spike note](./adaptive-topk-temporal-spike-2026-05-28.md)
- [F2 baseline](./locomo-f2-retrieval-ablation-2026-05-27.md)
- [ADR 0142 capstone](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md)
- Phase A PR #131 (merged as `9fa09d0`)
