# ADR 0144 — LoCoMo benchmark integration: Chimera's second eval surface

**Status**: Accepted (2026-05-26). Directional spike cleared the
pre-registered sanity rule on first land.

## Context

Every reliability artifact Chimera has built since ADR 0135 — ADR 0136
grounding, ADR 0140 stratified spike protocol, ADR 0142 `_s`-only
retrieval verdict, ADR 0143 oracle noise envelope, the T2.1d
deterministic-answerer falsification ([PR #89](https://github.com/elementalcollision/uberagent/pull/89))
— is conditioned on a single benchmark: LongMemEval. With one corpus we
cannot tell apart "Chimera-the-dialectic is robust" from
"Chimera-overfits-to-LongMemEval-shape." We need a second surface with
a meaningfully different conversational shape.

[LoCoMo](https://github.com/snap-research/locomo) (Maharana et al.,
ACL 2024, [arXiv 2402.17753](https://arxiv.org/abs/2402.17753))
provides exactly that: 10 simulated peer-to-peer conversations
averaging ~28 sessions each, spanning simulated weeks, with 1,986
question/answer pairs across five categories (single-hop, multi-hop,
temporal, open-domain, adversarial).

Where LongMemEval is curated user/assistant single-actor dialogue with
~3-session histories on the oracle subset, LoCoMo is multi-week
peer-to-peer with 19–32 sessions per conversation. The shape delta is
the entire point of the second surface.

## Decision

Integrate LoCoMo end-to-end into the Chimera eval stack as a peer
surface to LongMemEval. Specifically:

1. **Adapter** at [`chimera/evals/locomo.py`](../../chimera/evals/locomo.py)
   mirroring `chimera/evals/longmemeval.py` 1:1 in API and behaviour.
   Key shape delta: one LoCoMo `sample_id` produces many QA items
   sharing identical history, so the adapter caches ingest across
   sibling QAs.

2. **Grader** at [`scripts/grade_locomo.py`](../../scripts/grade_locomo.py)
   that re-uses LongMemEval's judge prompt families (single-hop /
   multi-hop / open-domain → "contains-correct-answer" template;
   temporal-reasoning → off-by-one tolerant template; adversarial →
   abstention-detection template). Same default judge
   (`openai/gpt-4o-mini`), same reasoning-judge blocklist + override
   knob from ADR 0143.

3. **CLI** verb `chimera evals locomo` with flag parity to `chimera
   evals longmemeval` (`--answer`, `--answer-model`,
   `--answer-temperature`, `--answer-max-tokens`,
   `--n-per-category`, `--hybrid-retrieval`, `--retrieval-top-k`,
   `--out`, `--mind-dir`) plus one new flag `--sample-id` for scoping
   a sweep to a single conversation.

4. **Hybrid retrieval wired from day one, default off**: LoCoMo
   conversations are uniformly above the default `top-k=8`, so the
   flag is meaningful immediately (unlike LongMemEval where it was
   `_s`-only). Default off preserves the upstream-paper-comparable
   full-context baseline.

5. **Tests**: 19 unit tests in
   [`tests/test_locomo.py`](../../tests/test_locomo.py) covering
   category mapping, sample-expansion, ingest cache, batch filters,
   grader prompt-template dispatch, and CLI flag wiring.

### Pre-registered decision rules (locked in design note)

1. **Directional spike** (n-per-category, target ~30 items): the
   chip's headline. Promotes to "LoCoMo is wired up correctly" if
   overall accuracy is non-degenerate (>20% on ≥3/5 categories).
2. **Sanity floor**: <10% overall → suspect plumbing. Diagnose; do
   not paper over with retries.
3. **Full corpus sweep**: operator-gated, deferred to follow-up chip.
   This chip does NOT need to clear any LoCoMo accuracy target.

### Directional spike result (n=30, gpt-4o-mini answerer + judge, T=0)

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| single-hop | 6 | 6 | **100.00%** |
| open-domain | 6 | 6 | **100.00%** |
| temporal-reasoning | 6 | 4 | 66.67% |
| multi-hop | 6 | 1 | 16.67% |
| adversarial | 6 | 1 | 16.67% |
| **overall** | **30** | **18** | **60.00%** |

- Overall non-degenerate (60.00% ≥ 10%): **PASS**.
- ≥3/5 cats above 20% (single-hop, open-domain, temporal): **PASS**.

ADR promotes to **Accepted** on first land. Full per-category structural
reading + caveats in
[locomo-baseline-spike-2026-05-26.md](../../mind/research/locomo-baseline-spike-2026-05-26.md).

### Comparison anchor (sanity, not a gate)

The LoCoMo paper reports closed-model accuracy/F1 in the **30–50%**
range on the full benchmark, with single-hop highest and adversarial
lowest. Our spike's overall 60% sits in the same order of magnitude
with the expected category ordering. Higher headline reflects LLM-judge
leniency vs F1/EM and a single-conversation sampling artifact (see
caveats in the baseline note).

## Consequences

### Immediate

- A second eval surface exists. Future "no regression" gates can be
  evaluated against both LongMemEval and LoCoMo and we can finally
  tell when a verdict is corpus-shape-specific.
- The judge model and prompt families are deliberately shared with
  LongMemEval. This keeps ADR 0143's noise-envelope characterisation
  potentially comparable across benchmarks (subject to the F3 follow-up
  re-characterising σ on LoCoMo).
- Multi-hop (16.67%) and adversarial (16.67%) per-cat numbers below the
  20% per-cat bar are structurally expected (see the paper's own
  difficulty ordering). They do not block the chip — the locked
  sanity rule is ≥3/5 cats ≥20%, met.

### What this chip's infrastructure unlocks (follow-up ladder)

These are **future chips**, not deliverables of this one. They are
mentioned here so the operator can charter them against a known
baseline.

| ID | Question this answers | Cost / time |
|---|---|---|
| **F1** | Full LoCoMo corpus sweep (1,986 items) — is the spike's 60% representative or a single-conversation artifact? | ~$5–10, ~70 min, operator-gated |
| **F2** | Does ADR 0142's `_s`-only retrieval verdict reproduce on LoCoMo's uniformly-long conversations? | depends on F1 baseline |
| **F3** | Does ADR 0143's σ envelope reproduce on LoCoMo with the same judge? | n=3 rerun pattern from T2.1c |
| **F4** | Where does Chimera's dialectic shine vs the model-strength ceiling observed in T2.1d? | cross-benchmark localisation |

F1 is the recommended next chip — it's the cheapest invalidation of
the single-conversation-bias concern in the spike note and unlocks
F2/F3/F4 by providing their no-flag reference.

### Non-consequences (explicit)

- **Existing LongMemEval baselines are not invalidated.** ADR 0142
  (`_s`-only retrieval) and ADR 0143 (noise envelope) remain in force
  on LongMemEval until F2/F3 produce evidence to the contrary.
- **The grader is not "the LoCoMo grader."** The upstream paper uses
  F1/EM; we use LLM-judge for cross-benchmark comparability with
  LongMemEval. Direct numerical comparison to the paper's table is not
  apples-to-apples.
- **No claim about Chimera's dialectic value.** This chip is wiring,
  not a value demonstration. F4 is where that claim gets tested.

## Alternatives considered

- **Skip the second benchmark, run more LongMemEval variants**:
  rejected because the T2.1d falsification already demonstrated we're
  at LongMemEval's model-strength ceiling on the oracle subset. More
  LongMemEval variants cannot answer the "is the verdict
  benchmark-shape-specific?" question.

- **Use a HuggingFace memory-eval (MSC, PerLTQA)**: rejected for
  scope. LoCoMo has the cleanest shape delta from LongMemEval (two-
  speaker peer-to-peer vs single-actor) and a published comparison
  anchor. Other benchmarks are candidates for a future third surface.

- **Default hybrid-retrieval on for LoCoMo from the start**: rejected
  because we want the no-flag baseline to be paper-comparable
  full-context. Hybrid-retrieval is exposed via flag so F2 can ablate.

## Linked

- ADR 0135: LongMemEval integration (the surface this is a peer to).
- ADR 0136: Grounding-content / timestamp surface (re-used in
  LoCoMo's "today" anchor at top of self-card).
- ADR 0140: Stratified spike protocol (this chip is an instance).
- ADR 0142: Hybrid retrieval (`_s`-only verdict — F2 cross-checks it).
- ADR 0143: Oracle noise envelope (F3 cross-checks it).
- `mind/research/locomo-design-2026-05-26.md`: locked-design note.
- `mind/research/locomo-baseline-spike-2026-05-26.md`: spike record.
