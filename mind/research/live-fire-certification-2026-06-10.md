# Live-fire certification round — 2026-06-10

Follow-up to the routing soak campaign
([routing-soak-campaign-2026-06-08.md](./routing-soak-campaign-2026-06-08.md)):
the #282 promotions set an explicit standard — **Accepted requires live-fire**
(the feature's behavior demonstrably executed in the live loop), not merely
armed-without-crashing. This round live-fires the remaining candidates.

## Exercise 1 — ADR 0172 Boltzmann selection (✅ FIRED)

Real splitter call (deepseek-v4-pro, `CHIMERA_BOLTZMANN_ALLOC=1`) on a
9-part telemetry task; budget K=3 over the parsed list, both branches
computed on the SAME live response:

- flag OFF (first-N): indices **[0, 1, 2]**
- flag ON (value-aware): indices **[2, 4, 6]** — the three artifact-naming
  sub-tasks (`subtask_value` 1.8 / 1.3 / 1.8), original order preserved.

First-N would have dropped both high-value artifact tasks. Selection is
demonstrably value-aware on real model output → **promotion criterion met**.

## Exercise 2 — soak `realtask-2026-06-10-0959` (0170 ✅ / 0171 ✗)

`real_task_soak` at HEAD `5b6d024`, all 6 routing/entropy flags ON plus
`CHIMERA_ENTROPY_SIGNALS=1` and `CHIMERA_FANOUT_MAX_WIDTH=1` (engineered so
ANY ≥2-wide tool batch trims). Task: fix the 4 ruff E702 findings in
`tests/test_soak_watchdog.py`. 54 api_calls, $0.215.

**ADR 0170 tool-use entropy — FIRED, 3 emissions, diagnostically meaningful:**

```
ACT: tool-use entropy H=0.0   over 23 tool call(s)   ← fixation, during the watchdog-quiet iter
ACT: tool-use entropy H=0.592 over 14 tool call(s)   ← mixed tool use, productive iter
ACT: tool-use entropy H=0.0   over 1 tool call(s)    ← single-call commit cycle
```

The H=0.0×23 reading coincided with the 600s silent-death watchdog iteration —
the signal read fixation exactly where the loop was in fact stuck, which is
the precursor behavior the ADR claims. **Promotion criterion met.**

**ADR 0171 fan-out budget — DID NOT FIRE (honest negative):** even at
width 1, the lead model (deepseek-v4-pro) emitted tool calls strictly one at
a time this run; there was never a ≥2-wide batch to trim. The budget cannot
fire if the model never fans out. Stays Proposed/compose-safe; firing it
needs either a model/prompt that batches calls or a synthetic multi-tool_use
provider response in a live loop.

**Soak outcome (operator handoff):** phase 1 verify-green in 2 iters; agent
self-committed (3 commits, incl. one `\x00MUT corruption` garbled message —
same artifact class as campaign cell 6). The harness-time gate read
`FAIL — ruff ✓ pytest ✗`, but the failure (`test_watchdog_clean_exit_returns_zero`)
is a watchdog TIMING test that ran while the soak loaded the machine;
post-run the worktree passes `chimera verify` twice consecutively
(PASS — ruff ✓ pytest ✓, 15/15 tests, same count as main — nothing deleted).

**Scope-creep flag (ADR 0173 advisory in action):** the diff is
+86/−182 across the whole file — a wholesale rewrite for a 4-semicolon task.
Per ADR 0173 this is surfaced, not blocked: deliverable is green but
provenance is messy and the rewrite's faithfulness to the original tests'
intent is unreviewed. **Recommendation: do NOT harvest; leave the 4 findings
as debt for a cleaner pass.** (Contrast: the morning run
`realtask-2026-06-10-0915` produced a clean in-scope fix that WAS harvested
as #281.)

## Status after this round

| ADR | Flag | Status |
|---|---|---|
| 0165 / 0166 / 0169 | prefilter / complexity / reheat | Accepted (#282) |
| 0170 | `CHIMERA_ENTROPY_SIGNALS` | **Accepted (this round)** — wiring #283, live-fired here |
| 0172 | `CHIMERA_BOLTZMANN_ALLOC` | **Accepted (this round)** — live value-aware selection |
| 0171 | `CHIMERA_FANOUT_BUDGET` | Proposed — armed-safe; awaits a real ≥2-wide batch |
| 0167 | `CHIMERA_PEER_SELECTION` | Proposed — awaits a multi-peer federation |

All flags remain default-OFF.
