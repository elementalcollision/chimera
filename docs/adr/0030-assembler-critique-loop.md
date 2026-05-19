# ADR 0030 — Assembler prompt refinement + critique-and-revise loop (v4.7)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0029](0029-assembler-ladder.md) (assembler ladder)

## Context

v4.6 added tier escalation but each tier still only got one shot.
Real-traffic mutation #1 (`synthesize_to_file`) parsed but scored
0.00 on validation; mutation #2 (`synthesize_to_file_v2`) failed at
the response-parse step on both sonnet and opus. The model wasn't
even reliably producing the expected fenced-block shape.

Two separate problems → two complementary fixes.

## Decision

### Prompt refinement: a worked example

The `ASSEMBLY_PROMPT_TEMPLATE` now opens with a complete worked
example (`reverse_string`) showing the exact three fenced blocks in
the exact order, including the JSON shape of the schema and the
samples array. Empirically, a single in-context exemplar lifts
parse-success substantially — the v4.7 spin saw opus go from
parse-fail (v4.6 mutation #2) to parse-success (mutation #3).

### Critique-and-revise: one feedback round per tier

New module `chimera/skills/critique.py`:

- `build_critique_prompt(spec, assembled, validation)` formats the
  failed handler, the per-sample outcomes, and the validator's
  reason into a revise-request.
- `critique_and_revise(...)` calls the same tier's provider, parses
  the response with the existing `parse_assembly_response`, returns
  the revised `AssembledSkill` (or `None` if the revision itself
  fails to parse). Records api_calls + ladder_outcomes rows under
  `task_type="skill_critique"` so dashboards distinguish original
  assembly from revision attempts.

`assemble_with_escalation` now does **per tier**:

```
assemble → validate
  ok → return immediately
  fail → critique_and_revise → validate
    ok → return (mark attempt revised=True)
    fail → escalate to next tier
```

`AttemptOutcome` gains `revised: bool` and `revised_score:
float | None` so the CLI / dashboard can show which attempts
involved a revision.

## Non-goals

- Only **one** revision per tier. Multi-round per-tier revision is
  marginal value vs. ladder escalation; revisit if a model gets
  closer than 0.5 score reliably but never crosses 0.6.
- No prompt-engineering loop. The critic prompt is fixed; we don't
  ask the model to design its own revise-prompt.
- No retroactive re-assembly of previously-failed mutations.
  Mutation #1 stays `failed`; operators can hand-create a new
  mutation if they want to retry.

## Tests

`tests/test_critique_loop.py` (4 cases):
- `build_critique_prompt` includes handler + outcomes + reason.
- Revision succeeds → ladder returns the revised assembly on the
  same tier, no escalation.
- Revision also fails → ladder escalates to the next tier.
- Critic returns None → attempt records `revised=False`.

Existing `tests/test_assembler_ladder.py` (4 cases) updated to use
`monkeypatch.setattr` on `critique_and_revise` to skip the new path
in non-critique tests.

Full suite: 482 passing.

## Live verification

Mutation #3 (`synthesize_to_file_v3`), hand-created with a tighter
brief:

```
[sonnet] assembly failed: missing one of the schema/python/samples fenced blocks
[opus]   passed 33% (ok=False)
ladder exhausted; no tier produced a valid skill.
```

The `ladder_outcomes` table now shows both `skill_assembly` and
`skill_critique` rows for opus on this run — proof the critic loop
fired. The skill still doesn't activate (33% < 0.6), and the
mutation is marked `failed` with the precise reason. Refinement
moved the bar; the bar held.

## Future paths if this stays brittle

- Use a stronger anthropic-direct model as the opus rung instead of
  the deepseek-v4-pro router currently selected by the OpenRouter
  rung. Edit `OPUS_LADDER` to put `OPUS` first.
- Hand-write the synthesis skill once (it's a small, well-bounded
  function) and skip the auto-proposer for this signature.
- Lower `validate_skill`'s default `pass_threshold` from 0.6 to 0.5,
  but only after we've seen enough runs to know 1/2 is genuinely
  better than 1/3.
