# ADR 0066 — Tier-aware adaptive budget (v4.47)

**Status:** Accepted (2026-05-19)

## Context

v4.5 made `max_rounds` adapt to task shape (declared artifacts + named
tools). v4.46 made the agent escalate tier when a task fails. But the
budget didn't follow: a task promoted from haiku to sonnet still ran
on a haiku-sized round budget. Opus, which costs more per round but
plans more deeply, was running on the same 12-round ceiling as the
cheapest model.

## Decision

`dynamic_max_rounds(task_text, *, base, per_artifact, per_tool, cap,
tier="haiku")` now applies a tier multiplier:

| Tier | Multiplier |
|---|---|
| haiku | 1.0× |
| sonnet | 1.5× |
| opus | 2.0× |

Both the shape-derived budget AND the cap are scaled, so opus on a
compound task can use up to 64 rounds (cap=32 × 2.0). The base round
floor scales too — `int(round(base * mult))`.

ACT passes `tier=self._tier` at call time, which means the v4.46
auto-promotion automatically gets the larger budget.

### Worked example

A haiku task at `base=12` lands at 12 rounds. After cycle-14-style
failure, v4.46 promotes to sonnet — and v4.47 hands sonnet 18 rounds
instead of 12. If sonnet also fails, v4.46 promotes to opus and v4.47
gives opus 24 rounds. The agent has measurably more headroom each
time it retries a hard task.

## Tests

`tests/test_adaptive_budget.py` — 5 new tests:

- `test_dynamic_max_rounds_haiku_is_baseline`
- `test_dynamic_max_rounds_sonnet_promotes_budget`
- `test_dynamic_max_rounds_opus_doubles_budget`
- `test_dynamic_max_rounds_opus_scales_the_cap_too`
- `test_dynamic_max_rounds_unknown_tier_defaults_to_haiku_multiplier`

Full suite: **563 passing**, 5 skipped (+5 new).

## Non-goals

- **Cost-per-tier-multiplier tuning.** 1.0 / 1.5 / 2.0 are first
  approximations. A future sprint can mine `api_calls` to see whether
  opus tasks actually consume their full budget or whether they could
  do with less.
- **Time budget per round.** Wall-clock per round isn't bounded by
  tier — the OPUS provider call IS slower but we don't yet scale the
  per-cycle phase budget. Worth a future ADR if cycles run long.
