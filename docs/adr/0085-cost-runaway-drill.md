# ADR 0085 — Cost runaway drill scenario (v4.66)

**Status:** Accepted (2026-05-20)

## Context

The v4.53–v4.60 cost-discipline arc shipped three orthogonal hard
stops (per-cycle, rolling-hour, per-task) plus retrospective and
prospective CLI surfaces. Each layer has unit tests; the arc has
no single end-to-end regression that proves the layers *compose
correctly* — i.e. that the same synthetic burn pattern triggers
each cap at the right boundary.

The other scenarios in `chimera/scenarios/` (drift, federation,
graph stress) follow this same shape: a single CLI invocation that
exercises a whole subsystem under known input and asserts known
outputs. The cost arc deserves the same.

## Decision

### `chimera/scenarios/cost_runaway_drill.py`

Hermetic regression — no API keys, no network, runs against a
temp DB:

```
run_cost_runaway_drill() -> CostRunawayResult
```

Procedure:

1. Open a temp `chimera.db` (the production DB is never touched).
2. Inject 5 synthetic `api_calls` rows mirroring the 2026-05-19
   burn: 600K input + 20K output on `claude-opus-4-7` per cycle,
   one per cycle, all attributed to the same task signature.
   Total simulated spend: 5 × $10.50 = **$52.50**.
3. Run four checks:
   - **per_cycle_cap** — `check_cycle_cost_cap(db, cycle=1)`
     must raise (cycle 1 alone spent $10.50 > $2 default cap)
   - **per_task_budget** — `check_task_budget(db, sig)` must raise
     (signature spent $52.50 > $5 default budget)
   - **rolling_hour_cap** — `check_rolling_hour_cost_cap(db)` must
     raise (60m spend $52.50 > $20 default cap)
   - **fresh_task_unaffected** — negative control: a different
     task signature must NOT trip the per-task budget ($0 spent)
4. Return a `CostRunawayResult` with a `CapTripCheck` per check;
   `result.ok` is True iff every check matched its expectation.

### `chimera scenario cost_runaway_drill` CLI

Reuses the existing `chimera scenario` umbrella. Prints a
formatted report and exits 0 on green, 1 on red:

```
chimera cost_runaway_drill: OK
  simulated 5 cycle(s), total $52.50
  ✓ per_cycle_cap             $ 10.50 vs $  2.00  → tripped
  ✓ per_task_budget           $ 52.50 vs $  5.00  → tripped
  ✓ rolling_hour_cap          $ 52.50 vs $ 20.00  → tripped
  ✓ fresh_task_unaffected     $  0.00 vs $  5.00  → no trip
```

### Pytest wrapper

`tests/test_cost_runaway_drill.py` calls `run_cost_runaway_drill`
and asserts each check passes. Runs in the standard `uv run pytest`
sweep so CI catches a regression even when the operator forgets
to invoke the scenario manually.

## Tests

`tests/test_cost_runaway_drill.py` — 5 tests:

- Drill end-to-end passes (`result.ok`)
- Per-cycle cap tripped with spend > cap
- Per-task budget tripped with spend > budget
- Rolling-hour cap tripped with spend > cap
- Fresh signature negative control NOT tripped

Full suite after v4.66: 725 passing (was 720, +5 new).

## Non-goals

- **No real burn replay.** This drill is synthetic. It doesn't
  spin up actual provider calls or measure real spend. A full
  end-to-end test against a sandboxed provider is a future
  enhancement; the synthetic version catches all the SQL +
  helper-function regressions.
- **No env override testing inside the drill.** The drill uses
  whatever caps the operator's environment defines. If an
  operator sets `CHIMERA_CYCLE_COST_CAP_USD=100`, the per-cycle
  check will not trip on $10.50 spend — that's correct behavior,
  but it means the drill expects defaults. Operators should run
  it with the defaults to validate.
- **No simulation of cap-recovery.** The drill stops at "did the
  caps trip?"; it doesn't simulate what happens after (e.g. that
  ACT exits with the right finish_reason and escalation memory
  doesn't promote the tier). Those are pinned in
  `test_cycle_cost_cap.py`, `test_rolling_hour_cap.py`, and
  `test_task_budget.py` respectively. The drill complements
  those rather than duplicating them.

## Why this shape

Why a scenario instead of just more unit tests? Because the cost
arc spans multiple modules (budget.py, escalation.py, entities.py,
the price table). A single function call that exercises all three
caps with a realistic-shaped burn catches integration-level
regressions that any single-module test would miss — e.g. the
v4.57 timestamp normalization bug, which only surfaced when the
rolling-window query met the actual ISO-formatted timestamps from
production. A unit test wouldn't have caught it; this drill
would have.

Why a temp DB? Because running a regression scenario against
production state risks contaminating it. The drill should be safe
to run at any time, on any agent, without affecting live cycles.
A `with tempfile.TemporaryDirectory()` is cheap and correct.

Why include a negative control? Because the strongest test of a
mechanism is showing it DOESN'T fire when it shouldn't. If a code
path accidentally attributed spend across signatures, the
`fresh_task_unaffected` check would catch it.
