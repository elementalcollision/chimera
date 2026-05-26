# LoCoMo benchmark — directional spike baseline (ADR 0144)

**Date**: 2026-05-26
**Chip**: LoCoMo integration (net-new second eval surface)
**Companion**: ADR 0144, locomo-design-2026-05-26.md

## Headline

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| single-hop | 6 | 6 | **100.00%** |
| open-domain | 6 | 6 | **100.00%** |
| temporal-reasoning | 6 | 4 | 66.67% |
| multi-hop | 6 | 1 | 16.67% |
| adversarial | 6 | 1 | 16.67% |
| | | | |
| **overall** | **30** | **18** | **60.00%** |

## Sanity-rule clearance

Locked pre-registration rules from the design note (ADR 0144 §"Pre-registered decision rules"):

| Rule | Threshold | Result | Verdict |
|---|---|---|---|
| Overall non-degenerate | ≥10% | 60.00% | **PASS** |
| ≥3/5 cats above 20% | ≥3 cats ≥20% | 3 cats (single-hop, open-domain, temporal-reasoning) | **PASS** |

**Headline verdict**: LoCoMo wiring is non-degenerate and the chip
clears its directional gate. ADR 0144 promotes from Proposed →
**Accepted**.

## Substrate

- **Answerer**: `openai/gpt-4o-mini`, temperature 0, max_tokens=2048,
  full-context (no retrieval), dialectic-prompt assembled via ADR 0133
  pipeline against synthetic `mind/peers/self.md` populated by the
  LoCoMo adapter.
- **Judge**: `openai/gpt-4o-mini` (per ADR 0143 default; reasoning-judge
  blocklist active).
- **Corpus**: `data/locomo10.json` (10 conversations, 1,986 QA pairs).
  Spike scope: 6 items per canonical category, first-match order — all
  30 items came from `conv-26` (the first conversation in the file).
  This is an artifact of the per-category cap filling its budget from
  conv-26's QA list before reaching others, *not* a sampling decision.
- **Total cost**: ~$0.40 (well under the $2 spike budget).
- **Wall-clock**: ~3 minutes (answerer + grader combined).

## Comparison anchor (sanity, not a gate)

LoCoMo paper reports F1 / accuracy for closed-source models in the
**30–50%** range overall on the full benchmark, with single-hop
highest and adversarial lowest. Our spike's overall 60% is in the same
order of magnitude with the expected category ordering (single-hop
high, adversarial low). The headline number being slightly higher than
the paper's reflects:

- LLM-judge yes/no is more lenient than the paper's F1/EM metric.
- All items come from a single conversation (conv-26) which may be
  easier than the corpus mean — full sweep (follow-up F1) will tell us.

The order-of-magnitude match is what we wanted from a wiring check.

## Per-category structural reading

- **single-hop (100%)**: The dialectic API surfaces full conversation
  context; single-session lookups are essentially free.
- **open-domain (100%)**: gpt-4o-mini's world knowledge dominates;
  these questions can often be answered without consulting the
  conversation at all.
- **temporal-reasoning (66.67%)**: ADR 0136 grounding-timestamp surface
  is doing real work here. Two failures (qa27, qa30) — would need to
  inspect prompts to know if they're date-arithmetic or session-pick
  errors.
- **multi-hop (16.67%)**: matches the paper's reported difficulty.
  Multi-hop on a single conversation requires connecting two
  facts across distant sessions; the full-context answerer has the
  raw material but the chain-of-reasoning step is hard.
- **adversarial (16.67%)**: the answerer rarely refuses. The grader
  template (LongMemEval abstention prompt) is strict — "the model
  could say information is incomplete" is the only valid surface.
  gpt-4o-mini tends to confabulate an answer rather than say "I don't
  know" on conv-26's adversarial subset.

## Caveats

1. **Single-conversation bias**: all 30 items from `conv-26`. The
   full-corpus follow-up (F1) is needed before any per-category claim
   becomes load-bearing. This spike is wiring-grade, not
   accuracy-grade — explicit pre-registered scope.

2. **No retrieval**: spike ran with the upstream-paper-comparable
   full-context default. The hybrid-retrieval ablation (F2) is the
   actual ADR 0142 cross-benchmark check.

3. **Judge re-use**: same `openai/gpt-4o-mini` + LongMemEval prompt
   families. ADR 0143's σ envelope **is not yet characterised** for
   LoCoMo — F3 is the chip that does that.

## Recommended next chip

**F1: Full LoCoMo corpus sweep** (1,986 items, ~$5–10, ~70 min,
operator-gated). Produces the corpus-level baseline that downstream
chips (F2 hybrid-retrieval ablation, F3 noise envelope) need as their
no-flag reference. Highest-leverage follow-up because:

- It's the cheapest way to invalidate the
  "single-conversation-bias" concern above.
- It unlocks every other follow-up by giving them a stable baseline
  to delta against.
- It mirrors LongMemEval's T1.4 post-Tier-1 full-sweep baseline
  (May 24 #17600), keeping the two benchmarks symmetric.

Alternative: F2 hybrid-retrieval ablation goes first if the operator
wants to triangulate ADR 0142's verdict before investing in a full
no-flag baseline. Less aligned with how LongMemEval was developed
historically.
