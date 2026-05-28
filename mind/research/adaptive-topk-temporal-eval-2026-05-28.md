# Adaptive top-k for temporal queries — Phase B gate-measurement (PENDING)

**Date**: 2026-05-28 (skeleton — awaits execution)
**Chip**: ADR 0142 capstone amendment, remediation direction #1 — *adaptive top-k for temporal queries*, Phase B
**Status**: **PENDING — operator-blocked: OPENAI_API_KEY missing in worktree environment.**
**Phase A**: [PR #131](https://github.com/elementalcollision/chimera/pull/131) (design + spike + implementation, default OFF, CI green)

## Blocker

The Phase B full-eval requires `OPENAI_API_KEY` to call the
`openai/gpt-4o-mini` answerer + judge (the F2 substrate that the
baseline numbers were measured against). The autonomous chip
environment did not have this key set:

```
$ test -n "$OPENAI_API_KEY" && echo SET || echo MISSING
MISSING
```

Other prerequisites are green:

| Check | Status |
|---|---|
| `OPENAI_API_KEY` | **MISSING** |
| `VOYAGE_API_KEY` | missing (acceptable — Ollama is the locked F2 dense backend) |
| Ollama @ `ollama.deploy.orb.local` | reachable |
| `/tmp/locomo/locomo10.json` corpus (1,986 items) | present |
| `scripts/grade_locomo.py` (locked grader) | present |
| Phase A code merged | NO (PR #131 operator-gated, not yet merged) |

## Pre-registered gate (LOCKED, copied from charter — DO NOT relax)

1. **Primary**: LoCoMo temporal-reasoning accuracy ≥+2pp vs F2 baseline (35.42% on n=96). Floor: **≥37.42%**.
2. **Overall regression guard**: overall LoCoMo accuracy across all 1,986 items must NOT drop below F2 baseline minus 1pp. Floor: **≥58.37%**.
3. **`_s` regression guard**: LongMemEval `_s` long-horizon accuracy must remain within ±3pp of existing `_s` baseline.
4. **Default-off**: gated behind env knob, default OFF. ADR 0142 status stays `Accepted (_s-only)` regardless.

If primary fails, this note ships as a falsification record. No
post-hoc gate relaxation. No re-labeling.

## Execution recipe

Once `OPENAI_API_KEY` is available and PR #131 is merged (or its
branch is checked out):

```bash
# Sanity: confirm env knob + key
export OPENAI_API_KEY=...                 # operator-supplied
export CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1   # the chip's knob
export CHIMERA_LOCOMO_TRACE=1
export PYTHONUNBUFFERED=1

# Mirror F2's exact invocation (locomo-f2-retrieval-ablation-2026-05-27.md §"Operational details > Invocation")
chimera evals locomo \
  --items /tmp/locomo/locomo10.json \
  --answer --answer-model openai/gpt-4o-mini \
  --answer-temperature 0 --answer-max-tokens 2048 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-adaptive-topk-locomo/results.jsonl \
  --mind-dir /tmp/chimera-adaptive-topk-locomo/mind \
  2>&1 | tee /tmp/chimera-adaptive-topk-locomo/sweep.log

# Grade with the locked judge (same as F2)
python scripts/grade_locomo.py \
  --in /tmp/chimera-adaptive-topk-locomo/results.jsonl \
  --judge openai/gpt-4o-mini \
  --out /tmp/chimera-adaptive-topk-locomo/results.graded.jsonl \
  2>&1 | tee /tmp/chimera-adaptive-topk-locomo/grade.log
```

Expected wall: ~3h 41m (mirrors F2). Expected spend: ~$8.50 (F2 was
~$8, plus ~$0.50 from running k=full on the 96 temporal items).
**Budget check**: $8.50 < $10 pause threshold — proceed without
re-surfacing to operator.

For the `_s` regression guard, separately run:

```bash
# n=30 stratified _s subset (ADR 0142's locked gate substrate)
CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1 chimera evals longmemeval \
  --items <_s-stratified-30> --variant _s \
  --hybrid-retrieval --retrieval-top-k 8 \
  --answer --answer-model openrouter/openai/o4-mini \
  --out /tmp/chimera-adaptive-topk-s/results.jsonl
# Then grade against ADR 0142's 66.67% pass-floor.
```

Note: the `_s` adapter (`chimera/evals/longmemeval.py`) currently does
NOT consume the `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` knob — this chip only
wired the LoCoMo adapter (per charter scope: ≤8 files,
implementation file ≤200 LOC additive). The `_s` guard therefore
measures whether the `is_temporal_query` regex (used by no path
currently in `_s`) perturbs `_s` accuracy via cross-talk; with the
adapter not consuming the knob, **the expected `_s` delta is 0.00pp**
(byte-identical to ADR 0142's gate result). If a future operator
wants to extend adaptive-top-k to `_s`, that's a separate chip.

## Reuse-vs-pair decision

Charter authorizes either. **Recommendation: reuse F2 baseline.** Per
Phase A spike note §"Second-pass full-corpus check": the in-harness
adaptive branch is gated strictly on `item.category == "temporal-reasoning"`,
so for the 1,890 non-temporal items the code path through
`_select_session_indexes` is **byte-identical to F2** (the new branch's
`if` condition is False for every non-temporal item; the existing
`select_top_k_sessions(...)` call runs unchanged). The overall
regression guard (≥F2−1pp) accommodates the F3 single-sweep
~92-flip floor (~4.6% of 1,986).

For the 96 temporal items, Phase B measures fresh and compares to
F2's 35.42% (34/96) — a paired n=96 sub-baseline could be added later
if the operator wants a cleaner Δ at additional cost (~$0.40 for an
n=96 adaptive-OFF sub-sweep).

## Per-category gate template (to be filled in)

| Category | n | F2 (adaptive-OFF) | Phase B (adaptive-ON) | Δ | Gate verdict |
|---|---:|---:|---:|---:|:---:|
| adversarial | 446 | 32.96% (147) | TBD | TBD | regression guard: ≥−1pp |
| multi-hop | 321 | 45.79% (147) | TBD | TBD | regression guard: ≥−1pp |
| open-domain | 841 | 85.49% (719) | TBD | TBD | regression guard: ≥−1pp |
| single-hop | 282 | 46.81% (132) | TBD | TBD | regression guard: ≥−1pp |
| **temporal-reasoning** | **96** | **35.42% (34)** | **TBD** | **TBD** | **PRIMARY: ≥+2pp (≥37.42%)** |
| **OVERALL** | **1986** | **59.37% (1,179)** | **TBD** | **TBD** | **regression guard: ≥58.37%** |

## Honest disclosures (pre-registered)

1. **Gate is conditional on `openai/gpt-4o-mini` judge + locked `scripts/grade_locomo.py` prompt.** Switching judge models retroactively would invalidate the gate without invalidating the design.
2. **The 19-item H2 dominance (74%) rests on agent classification, not independent ground truth** (per ADR 0142 §"Honest disclosures"). If H2 was over-called, the primary gate may fail honestly.
3. **Single-sweep caveat**: Phase B is one sweep. The F3 noise envelope (σ overall = 0.46pp) bounds interpretation; the +2pp temporal gate at n=96 is comfortably outside any plausible per-cat σ at that n.
4. **`_s` guard is structurally near-zero** — this chip did not extend adaptive-top-k to the `_s` adapter (scope-locked). The guard mainly confirms no cross-talk.
5. **Status remains `Accepted (_s-only)`** even if gate clears — operator decision.

## Action items for the operator

1. Provision `OPENAI_API_KEY` in a worktree (or run Phase B from operator's local env).
2. Check out PR #131 branch (or merge it).
3. Run the execution recipe above (~3h 41m wall, ~$8.50 spend).
4. Fill in the per-category table.
5. Make the primary-gate verdict call (clear / fail / partial).
6. Decide: ship Phase B PR with measured results, or close as falsified.

## Linked decisions

- [Phase A design note](./adaptive-topk-temporal-design-2026-05-28.md)
- [Phase A spike note](./adaptive-topk-temporal-spike-2026-05-28.md)
- [F2 baseline](./locomo-f2-retrieval-ablation-2026-05-27.md)
- [ADR 0142 capstone](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md)
- Phase A PR #131
