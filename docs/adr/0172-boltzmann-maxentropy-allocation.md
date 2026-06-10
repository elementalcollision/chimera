# ADR 0172 — Boltzmann max-entropy allocation (v4.120)

**Status:** Accepted (2026-06-10). Compose-safety validated in the post-fix
all-flags soak (flag armed throughout, no regression), then **live-fired**: a
real splitter call (deepseek-v4-pro) returned 9 sub-tasks; with the flag on
and budget 3, the value-aware selection kept indices [2, 4, 6] — the three
artifact-naming sub-tasks (`subtask_value` 1.8/1.3/1.8), order preserved —
where first-N would have kept [0, 1, 2] and dropped both high-value artifact
tasks. See
[live-fire-certification-2026-06-10.md](../../mind/research/live-fire-certification-2026-06-10.md).
Default remains OFF (`CHIMERA_BOLTZMANN_ALLOC`).

## Context

Under uncertainty about *which* sub-task is the bottleneck, Jaynes' maximum-
entropy principle says: don't prematurely commit the whole budget to one
branch — spread it as the maximum-entropy distribution consistent with the
known constraints, concentrating only as evidence accrues. Operationally that
is a **Boltzmann/softmax** allocation of a fixed budget over scored candidates
with a **temperature**: hot early (explore broadly, near-uniform), cooled as
confidence grows (exploit the best). This generalises today's flat caps — the
PLAN `MAX_PROPOSED_TASKS_PER_PLAN = 3` (`proposals/generate.py`) and the
splitter's `max_subtasks = 6` (`core/task_splitter.py`), both of which keep the
**first N** candidates with no scoring.

The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
(§3a, ranked #6) flags this as the **most speculative and most invasive** of
the six insertions: it needs a per-candidate *value estimate* the proposal and
split paths do not yet carry, and stochastic allocation is exactly the failure
mode the ADR 0072 cost caps exist to stop. So it ships as a pure primitive with
a single conservative, reversible wiring.

## Decision

A pure maximum-entropy allocation module; the splitter's flat truncation
becomes a value-aware selection behind a default-OFF flag.

### Code

- `chimera/core/allocation.py` — new module:
  - `boltzmann_allocation_enabled()` — honours `CHIMERA_BOLTZMANN_ALLOC`
    (default off; same shape as `peer_selection_enabled`, ADR 0167).
  - `allocation_temperature()` — honours `CHIMERA_BOLTZMANN_TEMP` (default 0.0
    = deterministic).
  - `softmax(values, temperature)` — Boltzmann weights; `temperature <= 0` is
    the zero-temperature limit (mass on the max, split across ties).
  - `anneal_temperature(t0, *, step, rate, floor)` — geometric cooling
    schedule (hot → cold as evidence accrues).
  - `allocate_budget(values, budget, *, temperature)` — integer apportionment
    (largest-remainder over softmax) that sums to `budget`; cold concentrates,
    hot spreads.
  - `boltzmann_select(items, values, k, *, temperature, rng)` — selects `k`
    preserving original order; **deterministic top-k by value** when
    `temperature <= 0` or no `rng` (the safe wired default), stochastic
    weighted sampling otherwise.
- `chimera/core/task_splitter.py`:
  - `subtask_value(text)` — pure specificity proxy: +1 for a declared
    `state/*`/`mind/*` artifact path, +0.5 for a recognised action verb (via
    `dedup.cluster_key`), +0.3 for fitting the < 800-char independence bound.
  - `split_task` — when the model returns more than `max_subtasks` **and** the
    flag is on, keep the highest-value `max_subtasks` via `boltzmann_select`
    instead of the first N. Flag off ⇒ `parsed[:max_subtasks]`, byte-identical.

### CLI / dashboard

None. Operator surface is the `CHIMERA_BOLTZMANN_ALLOC` / `CHIMERA_BOLTZMANN_TEMP`
env flags.

## Tests

`tests/test_allocation.py` — 27 cases: flag/temperature parsing;
`softmax` empty/singleton, sums-to-one, monotonic, hot-flatter-than-cold,
zero-temperature argmax + tie-splitting; `anneal_temperature` cools and floors;
`allocate_budget` sums to budget, cold concentrates, hot spreads evenly;
`boltzmann_select` k≥n returns all, deterministic top-k, order preservation,
tie-keeps-earliest, stochastic-with-rng returns k in order; `subtask_value`
rewards artifact paths; plus two `split_task` integration cases proving the
flag-off path keeps the first N (byte-identical) and the flag-on path keeps the
two artifact-naming sub-tasks. Existing `test_task_splitter` stays green (50
across the slice).

## Non-goals

- **Stochastic allocation in the hot loop.** The temperature-driven sampling
  (`allocate_budget`, `boltzmann_select` with an RNG) is provided and tested but
  the wired splitter path uses the **deterministic** branch (temperature 0,
  no RNG) — a value-aware replacement for "first N", nothing more. Turning the
  temperature up in production is a deliberate, separate decision and must stay
  inside the ADR 0072/0076/0079 cost caps.
- **Wiring the proposal path.** `extract_proposals` (`proposals/generate.py`)
  has the same first-N shape but no value signal at parse time; allocating the
  PLAN proposal/round budget via `allocate_budget` is the natural next caller,
  deferred until a proposal value estimate exists.
- **A learned value model.** `subtask_value` is a transparent heuristic proxy;
  replacing it with the critic's or an embedding score is future work.

## Why this shape

This is the speculative insertion, so it earns the most conservative wiring:
the only behavioural change anyone can opt into is "when forced to drop
sub-tasks beyond the budget, keep the most self-contained ones instead of the
first ones" — deterministic, reversible, and floored by the same `max_subtasks`
budget. The full Boltzmann machinery (temperature, annealing schedule, integer
budget apportionment) is built and unit-tested as a pure primitive so the
explore→exploit knob is ready for a deferred caller that has a real value signal,
without forcing stochasticity into the cost-capped loop today.
