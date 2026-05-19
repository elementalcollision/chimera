# ADR 0031 — Multi-witness critique + expanded opus ladder (v4.8)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0029](0029-assembler-ladder.md), [ADR 0030](0030-assembler-critique-loop.md)

## Context

v4.7 added a single-tier critique-and-revise loop. v4.7's live spin
showed opus's first-pass score climb from 0% → 33% after a self-
critique, but the activation threshold (0.6) wasn't crossed. The
remediation in the v4.7 ADR was explicit: use a stronger anthropic
rung as the first opus choice, and **add more flagship models from
other providers** so cross-witness critique has real diversity.

Operator framing: "Chimera (or its sub-agents) should call multiple
models to create, inspect, witness, and objectively critique
creations." That's a code-review committee pattern, not a single-
model retry loop.

## Decision

### OPUS_LADDER reordered + expanded (4 rungs)

```
0. claude-opus-4-7              (Anthropic, $15/$75 per Mtok, 200k ctx)
1. openai/gpt-5-pro             (OpenRouter, $2.50/$10, 400k ctx)
2. google/gemini-3-pro          (OpenRouter, $1.25/$5, 2M ctx)
3. deepseek/deepseek-v4-pro     (OpenRouter, $0.43/$0.87, 1M ctx)
```

Anthropic OPUS goes first because the v4.7 evidence pointed at it
being the strongest baseline for code-gen. The OpenAI + Google
flagship rungs broaden the model pool so cross-critique has real
disagreement to leverage. DeepSeek stays as the cost-optimised
safety net.

### New module: `chimera/skills/cross_critique.py`

`cross_critique(spec, assembled, validation, *, witnesses=("sonnet",
"opus"))` fans the critique-and-revise out across multiple tiers
**concurrently** (`asyncio.gather`). Each witness produces an
independent revision; each revision is validated; the highest-
scoring passing revision wins. Ties prefer the cheaper witness.

Returns a `CrossCritiqueResult` with `best_assembled`,
`best_validation`, `winning_witness`, and a per-witness
`WitnessOutcome` list (tier, revised_ok, score, failure_reason).

### Ladder integration

`assemble_with_escalation` grew a `witnesses: Sequence[str] | None`
parameter (default `("sonnet", "opus")`). On validation failure:

- `witnesses=None` → v4.7 single-tier critique (back-compat).
- `witnesses=(…)` → v4.8 cross-witness fanout.

`AttemptOutcome` gains `witnesses: tuple[str, ...]` and
`winning_witness: str | None` so per-attempt telemetry shows
exactly which models were consulted and which one's revision won.

### CLI

- `chimera tiers` (new) — print every tier ladder with per-rung
  costs and context windows. Helps operators verify which model the
  router will actually hit.
- `chimera skills assemble` output now includes `revised=`,
  `witnesses=`, and `winner=` per attempt so the cross-witness
  story is visible.

## Why concurrent witnesses, not sequential

Sequential is cheaper but slower; concurrent burns more tokens but
the wall-clock saving usually outweighs the cost when 2-3 witnesses
all finish in a few seconds. The mutation queue still gates the
whole flow, so the operator approves total cost up front.

## Non-goals

- **No automatic model-availability probing.** If OpenRouter doesn't
  serve `openai/gpt-5-pro` in your region, that rung's calls fail
  and the next rung takes over via the existing retry/escalation
  machinery. We don't pre-flight which models exist.
- **No witness disagreement metric.** Two witnesses producing
  different valid revisions are both fine — we pick the higher
  score, not the one that "agrees" with the other. Disagreement
  scoring is future work.
- **No cost-aware witness selection.** Operators can pass
  `witnesses=("sonnet",)` to skip opus if cost matters; we don't
  auto-prune.

## Tests

`tests/test_cross_critique.py` (6 cases):
- OPUS_LADDER starts with Anthropic OPUS after the reorder.
- OPUS_LADDER includes OpenAI + Gemini rungs.
- `cross_critique` picks the highest-scoring witness.
- Ties prefer the cheaper (earlier) witness.
- All witnesses fail → returns `winning_witness=None`.
- Ladder integration: cross-critique result surfaces in
  `AttemptOutcome` with witnesses + winning_witness recorded.

Updated test_providers.py (split the symmetry-invariant into two
tests; opus now has a different shape) and the v4.6/v4.7 tests
(pass `witnesses=None` to exercise the legacy single-tier path
those tests were written against).

Full suite: 489 passing.

## Live verification

Mutation #4 (`synthesize_to_file_v4`):

```
[sonnet] base=33%  revised=...  witnesses=sonnet,opus  winner=None  ok=False
[opus]   base=0%   revised=...  witnesses=sonnet,opus  winner=None  ok=False
ladder exhausted; no tier produced a valid skill.
```

The mechanism worked — cross-witness fanout fired on both tiers,
all witness scores were recorded, the mutation correctly failed at
0.00. The specific skill remains hard (the validator wants stdout-
substring matches and the natural implementation writes to a file
+ returns a confirmation), so the gate held even with the wider
model pool. The right next move for THIS skill is to hand-craft
it; the right next move for the **mechanism** is to log the
per-witness telemetry to the dashboard so operators can see which
models are good at which task types.
