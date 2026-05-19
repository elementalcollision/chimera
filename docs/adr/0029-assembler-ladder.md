# ADR 0029 — Skill-assembler tier escalation (v4.6)

**Status:** Accepted (2026-05-19)
**Mirrors:** [ADR 0024](0024-act-ladder-escalation.md) (ACT ladder)

## Context

v4.5 closed the L-3 fragmentation loop by auto-emitting a
`skill_proposal` mutation when a compound task fragments. The first
real-traffic run of that loop produced mutation #1 (`synthesize_to_file`),
which the operator approved, the v1.2 assembler ran on a single tier
(sonnet default), the validator scored 0.00/3, and the mutation
correctly failed at the validation gate — no broken skill landed.

But the assembler used **one** tier. The ACT executor since v3.11 has
walked the model ladder on failure; the assembler did not. Same code
shape, different code path — the symmetry was inviting.

## Decision

New module `chimera/skills/ladder.py` with
`assemble_with_escalation(spec, providers, db, cycle,
tiers=("sonnet", "opus"))`. For each tier:

1. Call `assemble_skill(spec, …, tier=tier)`.
2. If assembly itself fails (bad parse, no provider), record the
   attempt and continue to the next tier.
3. Otherwise call `validate_skill(assembled)`. If
   `validation.ok` → return immediately with `winning_tier=tier`.
4. If exhausted, return `winning_tier=None` and the last attempt's
   assembled + validation (so the caller can mark the mutation
   `failed` with the most-recent failure detail).

Per-attempt outcomes are captured in `LadderResult.attempts`
(`AttemptOutcome(tier, assembled_ok, validation_score, validation_ok,
failure_reason)`). The CLI prints one line per attempt and the
winning tier (or "ladder exhausted").

The CLI `chimera skills assemble <mut-id>` now uses the ladder
exclusively. The old single-tier `assemble_skill` remains for
programmatic callers and tests.

## Why "sonnet → opus" and not "haiku → sonnet → opus"

Skill assembly is a code-generation task with strict structural
output expectations. Haiku at v1.2 was already known to be unreliable
here. Starting from sonnet matches the prior default; opus is the
safety net. If a future failure mode wants finer granularity, the
`tiers=` arg accepts any sequence.

## Non-goals

- No retry within a single tier (the v3.5 `retry_call` machinery
  already covers transient provider errors).
- No mid-validation prompt repair. The model either produces the
  shape we asked for, or we escalate.
- No automatic re-proposal when ladder exhausts. The mutation queue
  records the failure; v4.5's auto-proposer will re-emit if the
  source task fragments again.

## Tests

`tests/test_assembler_ladder.py` (4 cases):
- ladder escalates sonnet → opus when sonnet validation fails
- ladder stops on first passing tier (no wasted escalation)
- exhausted ladder returns `winning_tier=None` and the last failure
- assembly failure on a tier is recorded and the ladder moves on

Full suite: 478 passing.

## Live verification

Mutation #2 (hand-created retry of the L-3 auto-proposal). With
`assemble_with_escalation`, both sonnet and opus attempted
assembly; both failed at the parse step (no `schema/python/samples`
fenced blocks). Mutation marked `failed, reason: ladder exhausted`.
The dashboard's All mutations section now shows distinct failure
reasons for #1 ("validation: score 0.00 < 0.6") and #2
("ladder exhausted") — two different gates fired in sequence.
