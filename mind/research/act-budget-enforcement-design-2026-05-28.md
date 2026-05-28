# ACT-phase budget enforcement — design note

**Date**: 2026-05-28
**Author**: chimera (agent)
**Closes**: PR #106 postmortem recommendation #6 (v35 attempt #3 ladder)
**Touches**: `chimera/core/loop.py`, `tests/test_loop.py`

---

## Problem

The v35 attempt #3 soak postmortem
([v35-soak-postmortem-2026-05-28-final.md](v35-soak-postmortem-2026-05-28-final.md))
recorded ACT-phase durations far in excess of the 240s budget hard-coded
in `run_one_cycle`:

| Iter | Phase | ACT duration | Ratio over 240s |
|---|---|---|---|
| 1 | phase 1 | 555s | 2.3× |
| 2 | phase 1 | 370s | 1.5× |
| 3 | phase 1 | 600s+ | 2.5×+ (watchdog) |
| 4 | phase 2 | 2017s | **8.4×** |
| 5 | phase 2 | 1336s | 5.6× |
| 6 | phase 2 | 1301s | 5.4× |

The 240s `budget_ms` argument to `_run("act", ...)` flowed into
`phase_timer`, where the only effect was emitting a WARNING log line if
the phase exceeded budget. The 600s silent-death watchdog (ADR 0120) was
the only mechanism actually capping ACT duration, and on iter 4 phase 2
the agent ran for 2017s before either watchdog or natural completion
intervened.

Symptom-independent of the v35 confabulation problem, this is a real
operational defect: a budget that does not enforce is a measurement, not
a control.

---

## Option A (chosen): enforce the budget via `asyncio.CancelledError`

Wrap the `_phase_act` coroutine in `asyncio.wait_for(timeout=budget)`.
On timeout the in-flight tool-use loop receives `CancelledError`, a
structured `act_budget_exceeded` event is logged, and the loop advances
to WRITE/FLUSH/COMMIT with whatever partial `_act_results` accumulated.

### Knob

`CHIMERA_ACT_BUDGET_SECONDS` (float, default **240.0**). Invalid or
non-positive values fall back to the default. The 240s default matches
the v35 baseline — operators who observed the overruns can dial it up
explicitly if they want a softer floor.

### Why not Option B (raise the default to 1200s + log only)

The pre-registered criterion locks Option A unless cancellation has a
structural blocker. I audited the ACT executor for two specific blocker
patterns:

1. **SQLite inconsistency.** `record_api_call` and
   `record_ladder_outcome` (chimera/core/act.py:1861, :1907) run
   *after* the provider call returns, between awaits. There is no
   pattern of partial multi-statement write that a `CancelledError`
   would tear in half. SQLite writes are atomic at statement
   granularity.
2. **Mid-response token waste.** `provider.complete_with_tools` is an
   awaitable HTTP call. Cancelling mid-stream drops the partial response
   on the floor and the token spend is invisible to our `api_calls`
   ledger. This is a real (mild) loss — but it is bounded by per-call
   cost, while the v35 data shows the *unbounded* alternative routinely
   burning 5–8× the intended budget on flailing retries. Cancellation
   reduces total cycle waste even after this leak.

No structural blocker found. Option A is safe.

### What would have happened on attempt #3

Iter 4 phase 2 (the 2017s outlier) would have been cancelled at 240s,
the loop would have advanced to REFLECT/WRITE, and the trust engine's
`scope_evasion` guard would have had its normal opportunity to demote
trust on the partial result rather than waiting another 30 minutes for
a confabulated commit to land. Iters 5 (1336s) and 6 (1301s) — where
the agent was arguably doing real planning work the watchdog never
truncated — would *also* have been cut to 240s; whether that's net good
depends on whether the planning work was actually productive. Per the
postmortem's substantive verdict (MIXED, confabulated breakdown), the
balance of evidence is that none of these overruns produced converging
work, so Option A's aggressive cancellation is the correct default.

### Honest disclosures

- **The 240s default was never empirically validated.** It was an
  aspirational hint inherited from the PLAN phase's identical budget,
  not a measured working-time floor. The v35 attempt #3 data is the
  first sustained measurement. If operators see legitimate work
  consistently exceeding 240s after this lands, the env knob is the
  intended escape hatch — but the burden of proof now lies with the
  data, not with silent overrun.
- **First soaks after this land may see premature ACT exits.** If a
  phase that previously ran 555s is now cancelled at 240s, the next
  iteration starts from a more truncated state. That is the cost of
  having a real budget. Operator can raise via env.
- **No new ADR.** This is a behaviour change to an existing knob
  (`budget_ms` → cancel-and-replan), not a new architectural decision.
  Existing engine guards (`scope_evasion`, `degenerate_loop_abort`,
  `witness_rejected`) and the 600s silent-death watchdog continue
  unchanged.

---

## Scope (locked, observed)

- `chimera/core/loop.py` — `_act_budget_seconds()` helper +
  `_run_act_phase_with_budget()` dispatch wrapper.
- `tests/test_loop.py` — three new tests:
  `test_act_budget_cancels_at_threshold`,
  `test_act_phase_in_budget_passes_through`,
  `test_act_budget_seconds_env_default`.
- This design note.

Total files touched: **3** (≤5 budget honoured). No ADR amendment
included — none of the existing ADRs (0003, 0120) needed to change.
`chimera/_async_loop.py`, the SQLite store, the silent-death watchdog,
and all soak scripts were not modified.
