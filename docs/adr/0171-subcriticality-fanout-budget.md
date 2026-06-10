# ADR 0171 — Subcriticality fan-out budget (branching process, v4.120)

**Status:** Accepted (2026-06-10). Compose-safety validated in the post-fix
all-flags soak (flag armed, no regression), then **live-fired end-to-end via
model-backed peers (ADR 0174)**: a live ACT run (deepseek lead, width budget
2) drew a real 3-wide `tool_use` batch of `mcp-model-*-consult` calls; the
budget dispatched 2, deferred 1 with the synthetic re-issue result
(`act: fan-out budget — dispatching 2 of 3 tool_uses, deferring 1`), the
model re-issued the deferred call the next round, it succeeded, and ACT
completed with a genuine three-model synthesis. The full trim → defer →
recover → complete contract executed live. See
[live-fire-certification-2026-06-10.md](../../mind/research/live-fire-certification-2026-06-10.md)
round 2. Default remains OFF (`CHIMERA_FANOUT_BUDGET`).

## Context

Chimera's self-decomposition (PLAN proposals, task splits, sub-agent recursion,
parallel tool fan-out) is a **Galton–Watson branching process**: each task
spawns a random number of children with mean offspring μ. With μ > 1 and
unbounded depth the work tree explodes — exactly the cost-runaway the fixed
`max_depth=2` (`tools/subagent.py`) and the three cost caps
([ADR 0072](0072-cost-runaway-guards.md)) exist to prevent. Those caps are a
*crude* branching-process control.

The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
(§2c, ranked #3) flags the one place that is genuinely **uncapped**: parallel
tool fan-out at `core/act.py` is `asyncio.gather` over *whatever the model
emits* — unbounded width. A branching/value lens caps it: the marginal value of
the w-th simultaneous probe has diminishing returns, so stop widening past a
budget.

## Decision

A pure branching-budget module; the fan-out width cap is wired into ACT behind
a default-OFF flag. The principled subcriticality helpers are provided for the
recursion side (follow-up wiring), keeping the change inside the existing caps.

### Code

- `chimera/core/branching.py` — new module:
  - `fanout_budget_enabled()` — honours `CHIMERA_FANOUT_BUDGET` (default off;
    same parsing shape as `peer_selection_enabled`, ADR 0167).
  - `fanout_max_width()` — honours `CHIMERA_FANOUT_MAX_WIDTH` (default 8, floored
    at 1 so a round can always make progress).
  - `fanout_split(width, max_width)` — **pure** `(dispatch, skip)` split: the
    first `max_width` calls (the model's order is its priority) dispatch, the
    rest defer.
  - `is_subcritical(mu, p_continue)` — the `μ·p_continue < 1` boundedness test.
  - `expected_branching_total(mu, depth)` — `Σ μ^d`, the geometric series the
    flat depth cap bounds bluntly.
  - `subcritical_depth_budget(mu, *, hard_cap)` — "deeper when each level is
    cheap, shallow when expensive," never beyond `hard_cap` (preserves ADR 0072).
- `chimera/core/act.py` — at the parallel fan-out `asyncio.gather`: when the
  flag is on, dispatch the first `fanout_max_width()` tool calls and return a
  synthetic **deferred** `ToolResultBlock` (`is_error=True`, "re-issue in a
  subsequent round") for the rest. This preserves the provider contract — every
  `tool_use` still gets a matching `tool_result`, in order — while capping
  width. Flag off ⇒ all calls dispatched, byte-identical to the prior gather.

### CLI / dashboard

None. Operator surface is the `CHIMERA_FANOUT_BUDGET` / `CHIMERA_FANOUT_MAX_WIDTH`
env flags.

## Tests

`tests/test_branching.py` — 23 cases: flag + width parsing (default 8, floored
at 1, bad-value fallback); `fanout_split` under/over/exact budget, width floored
at 1, zero width; `is_subcritical` below/at/above 1; `expected_branching_total`
linear at μ=1, geometric (μ=2,depth2 ⇒ 7), negative-depth = 0, grows with μ;
`subcritical_depth_budget` uses the hard cap when μ≤1, cheaper branching earns
≥ depth, never exceeds the hard cap. Existing `test_act` / `test_act_completeness`
stay green (55 passing, 1 skipped) — confirming the flag-off path is unchanged.

## Non-goals

- **Replacing the cost caps.** The fan-out budget sits *inside* the ADR 0072 /
  0076 / 0079 caps — stochastic/branching allocation is exactly the failure mode
  they were built to stop, so they stay authoritative and run regardless.
- **Wiring subcriticality into sub-agent depth.** `subcritical_depth_budget`
  and `is_subcritical` are provided and tested, but the `max_depth=2` hard gate
  in `subagent.py` is left in place; replacing the flat depth with a μ-aware
  budget is a separate, behaviour-changing follow-up that must still floor at
  the existing cap.
- **Entropy-informed width.** Trimming further when the fan-out's tool-type
  entropy (ADR 0170) says the extra calls are redundant is a natural composition,
  deferred to keep this change a single concern.

## Why this shape

Capping width by *deferring* (not dropping) the over-budget calls is what keeps
the change safe in the hot loop: the provider's "every tool_use needs a
tool_result" invariant is preserved, the model is told precisely how to recover
(re-issue next round), and with the flag off the code path is the original
`list(asyncio.gather(...))` exactly. The branching helpers stay pure so the
math is unit-tested without a provider, matching ADR 0167–0170.
