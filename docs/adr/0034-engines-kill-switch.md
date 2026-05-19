# ADR 0034 — Engines kill-switch covers planner + daily engines (v4.12)

**Status:** Accepted (2026-05-19)
**Closes:** L-4 in [docs/limitations.md](../limitations.md)

## Context

v4.2 introduced `CHIMERA_ENGINES_ENABLED=0` to let operators run an
ad-hoc cycle without paying the 60–90s engine cost. The env-var
check landed inside `EngineScheduler.pick_due`, which gated the
daily Discovery / Curiosity / Reflection engines. Live spins at
v4.5 onwards exposed the gap: `_phase_plan` has **two** paths —

1. **`Planner.maybe_plan`** (Opus, every Nth cycle, default N=4).
   Runs first. No env check.
2. **`_maybe_run_engine`** (daily engines via the scheduler).
   Runs only when the planner is skipped. Env-checked.

So when the cycle number aligned with the planner cadence, the
operator's `CHIMERA_ENGINES_ENABLED=0` was ignored and Opus fired.

## Decision

Single gate at the top of `_phase_plan`. When the flag is `0`, log
`PLAN: skipped (engines disabled)` and return. Covers both the
planner and the daily engines under one flag, which matches operator
intent (when they say "no engines today" they mean *all* engine-like
work, not just one of the two paths).

## Why one gate, not two

Two gates was the alternative — distinct env vars for planner vs.
daily engines. Rejected because:

- The operator-facing concept is "engine work", undifferentiated.
- The cost shape is the same (one Opus call ≈ one daily-engine run).
- Two env vars doubles the surface for typos and forgotten flags.

If we ever need finer control, add a positional argument; don't
proliferate env vars.

## Non-goals

- No retroactive change to the daily-engine scheduler check. It
  stays where it was (consistent dual-coverage, defence in depth).
- No CLI flag mirror for `chimera run --no-engines`. The env var is
  the single source.

## Tests

`tests/test_loop.py::test_engines_kill_switch_gates_plan_phase` —
sets `CHIMERA_ENGINES_ENABLED=0`, sets
`config.opus_plan_every_n_cycles=1` (so the planner *would* fire),
runs one cycle, asserts the PLAN log line is the skip message,
`phase_times_ms["plan"] < 100`, and `proposals_added == 0`.

Full suite: 497 passing.
