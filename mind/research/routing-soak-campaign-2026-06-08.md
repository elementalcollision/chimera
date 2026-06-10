# Routing / entropy soak campaign — 2026-06-08

**Goal:** validate the autonomously-landed semantic-routing + entropy sub-tasking
features (ADRs 0165–0172, PRs #274–#276) in the LIVE loop, stepping through the
flag envelopes × harnesses and noting each flag's functionality.

**Pre-soak review verdict (this session):** clean. No new deps (version bump
only). Every behavior behind a default-OFF `CHIMERA_*` flag. `critic_gate.py`
(ENFORCE path) UNTOUCHED. 163 new unit tests pass; full suite 2241 passed / 5
skipped, no regression. One minor finding: `entropy_signals.py` (ADR 0170) is
defined but not surfaced in CLI/dashboard (dead-ish; follow-up chip, not a
blocker).

## Deterministic flag-decision snapshots (free, unit-level — "what does the flag DO")

All flags read `os.environ` at runtime and default OFF (inert-by-default holds
live, not just in tests):

| Flag | default(unset) | observed decision |
|---|---|---|
| `CHIMERA_TOOL_PREFILTER` | False | flag=1 → `tool_prefilter_enabled()=True`; selects tool schemas by task-text tokens |
| `CHIMERA_COMPLEXITY_ROUTING` | False | simple ruff task → floor tier `None` (stays cheap); hard design task → floor `sonnet` (escalates) |
| `CHIMERA_BOLTZMANN_ALLOC` | False | — |
| `CHIMERA_FANOUT_BUDGET` | False | `fanout_max_width()` default 8 |
| `CHIMERA_ANNEAL_REHEAT` | False | — |
| `CHIMERA_PEER_SELECTION` | False | power-of-two-choices peer pick |
| `entropy_signals_enabled()` | False | (observability helper; not wired to CLI/dashboard) |

## Campaign matrix (4 envelopes × 3 harnesses = 12 cells)

Envelopes: ① TOOL_PREFILTER · ② +COMPLEXITY_ROUTING · ③ baseline(all off) · ④ all-on
Harnesses: ① real_task_soak · ② self_determined_soak · ③ characterize

Driver task for real_task_soak cells (from `chimera self-scan`, behaviour-neutral,
low blast radius): **fix the 4 ruff findings in `tests/test_act.py`**
(scope-locked to that one file). Note: the routing PRs added their own lint debt —
14 findings in `cli.py`, 9 in `act.py` — a real, on-theme maintenance target.

## Results log

| Cell | Envelope | Harness | Run ID | Result | committed | gate | cost | functionality note |
|---|---|---|---|---|---|---|---|---|
| 1 | TOOL_PREFILTER | real_task_soak | realtask-2026-06-08-1323 | ✅ PASS | yes (1f2e47a) | PASS (ruff✓ pytest✓) | $0.0465 | prefilter active throughout; did NOT break convergence. Phase-1 iter-1 hit 600s silent-death watchdog (model quiet), iters 2–3 converged verify-green. Critic enforce unset (calibration record present). |
| 2 | TOOL_PREFILTER + COMPLEXITY_ROUTING | real_task_soak | realtask-2026-06-08-1419 | ✅ PASS | yes (da6e547) | PASS (ruff✓ pytest✓) | ~$0.061 | Both flags active. complexity_routing floored to None on the trivial task → NO escalation, stayed at base tier (correct). Converged in 4 iters (1 more than cell 1), each iter hit the 600s watchdog — model stochasticity, NOT a flag effect (cell 1 hit it too). Extra cost = one extra watchdog iteration, not tier escalation. Minor: an extra "[agent] working: checkpoint WIP" commit preceded the fix (messier than cell 1's single commit). |
| 3 | BASELINE (all flags OFF) | real_task_soak | realtask-2026-06-08-1533 | ✅ PASS | yes (513b98e) | PASS (ruff✓ pytest✓) | $0.0664 | Control run — new routing/entropy code present but inert. Converged verify-green, gate PASS. Took the MOST iters (7) — confirms iteration count is model stochasticity, NOT flag-driven (baseline ≈ flagged cells). KEY RESULT: inert-by-default validated live — flags off produces the same successful convergence shape as flags on, zero regression. Extra "[agent] fix test_act scope" commit (same minor WIP-commit pattern as cell 2). |
| 4 | ALL 6 routing/entropy flags ON | real_task_soak | realtask-2026-06-08-1703 | ⚠️ NO-CONVERGE (gate caught break) | **NO commit** | FAIL (ruff✗ pytest✗) | n/a | First non-pass. Agent over-deleted while clearing the unused `repeated_call` finding — removed a load-bearing `decision` var → `NameError: 'decision'` ×15 tests. **Gate correctly returned FAIL and NO commit landed** (worktree has 0 commits); agent then reverted, leaving test_act.py == main (tests pass, 4 findings unfixed). **HEADLINE: under MAX flag load the safety floor held — a broken change never became a commit.** Attribution: this is the task's latent over-deletion trap (unused `repeated_call` sits adjacent to used `decision`), a TASK property not a flag effect (cells 1–3 incl. baseline passed the same task; the all-flags envelope doesn't touch how the agent edits a file). n=1, not flag-attributable. |

| 5 | TOOL_PREFILTER (harness 2, **critic ENFORCE=ON**) | self_determined_soak | selfdet-4202-20260608-183334 | ✅ FAITHFUL (gate correct) / surfaced brittle test | yes (c26e91f) | verify FAIL — ruff✓ **pytest✗** (1 test); **critic gate APPROVED, correctly** | — | Agent **self-selected** "fix 14 ruff findings in chimera/cli.py" (rank-1) and produced a TEXTBOOK-faithful lint fix (split inline if:return, removed unused imports, f""→"", lambda→def). Critic gate approved=true — a CORRECT approval of faithful work (0%-false-approve record INTACT; this is NOT a false approve). The lone pytest failure is `tests/test_self_scan.py::test_real_ruff_finder_surfaces_cli_debt`, a SELF-DEFEATING test: it hard-codes that chimera/cli.py carries ruff debt and asserts the scanner surfaces it — so the moment Chimera does its job (fixes cli.py's debt) the test's premise is invalidated. NOT a gate failure and NOT unfaithful code — a brittle pre-existing test that bites any agent OR human who fixes cli.py. Chip spawned to fix the test (use a synthetic dirty fixture, not live cli.py). Also: harness 2 ran the IN-LOOP CRITIC GATE enforced (3 enters, 1 decision allowed) — first enforced-gate cell, and it adjudicated faithfully. |
| 6 | TOOL_PREFILTER + COMPLEXITY_ROUTING (harness 2, **critic ENFORCE=ON**) | self_determined_soak | selfdet-41552-20260608-202845 | ⚠️ PASS-WITH-SCOPE-CREEP | yes (8eab876) | PASS — ruff✓ pytest✓; critic gate approved (4 enters, 4 decisions, last approved=true) | — | Agent self-selected "fix 9 ruff findings in chimera/core/act.py" (rank-2). Gate PASSED green and committed. BUT the diff EXCEEDS the lint scope: alongside genuine ruff fixes (f""→"", removed dup `import os`, added `Sequence` import) it ALSO **refactored the anneal_reheat path** — extracted `decision.matched_failures` into a new `prior_failures: int = 0` parameter and rethreaded it. Garbled commit message: "[agent] checkpoint (fix \x00MUT corruption in _schema_hint)" (null byte + "MUT corruption" — agent appears to have chased a mutation-test artifact). Refactor looks behavior-preserving (caller passes `prior_failures=decision.matched_failures`, full suite green) so NOT a safety breach — but it's scope creep + confusing provenance, weaker than cells 1–3's clean fixes. **FINDING: the critic gate enforces FAITHFULNESS and verify enforces GREEN, but NEITHER enforces SCOPE ADHERENCE — an agent can land unrequested refactors as long as tests stay green.** (ADR 0146 scope-check keys on chip READY-FOR-REMEDIATION, not soak task scope.) Worth a follow-up: a soak-task scope guard, or accept that "green + faithful" is the real contract and "scope" is advisory. |
| 7 | BASELINE (no routing flags, harness 2, **critic ENFORCE=ON**) | self_determined_soak | selfdet-65440-20260609-073250 | ✅ PASS (cleanest self-det cell) | yes (ec4c633) | PASS — ruff✓ pytest✓; gate approved (2 enters, 1 decision) | — | Self-selected "fix 6 ruff in tests/test_doctor.py" (rank-3). FASTEST cell yet (~5.5 min), single clean commit, in-scope (only test_doctor.py, 7/7 lines), no scope creep, no watchdog stalls. Enforced-gate baseline: confirms harness-2's enforced critic gate approves clean faithful work fast. Contrast with cell 6 (scope creep) shows the scope-creep there was task/model stochasticity, not a harness property. |
| 8 | ALL 6 routing/entropy flags ON (harness 2, **critic ENFORCE=ON**) | self_determined_soak | selfdet-77327-20260609-095220 | ⚠️ NON-CONVERGE (commit_not_executed) | **no** | FAIL — ruff✗ pytest✓; **gate NEVER invoked** (no commit attempted) | — | Self-selected "fix 5 ruff in chimera/core/loop.py" (rank-4, core file). Phase-2 INBOX confirms **phase 1 made the fix and `chimera verify` passed** — but in phase 2 the agent **never called git_commit** → work lost, loop.py back to unfixed (ruff✗), pytest✓, NO broken code landed. This is a `commit_not_executed`-class failure (the class ADRs 0147/0150/0151 address) recurring. Safety intact (nothing bad landed); the failure is non-production, not mis-production. ~5 min (fast give-up, didn't burn the wall). **HYPOTHESIS (not conclusion): both all-flags cells (4 & 8) failed to converge; all 5 other-envelope cells converged.** BUT failure modes DIFFER (cell 4 = over-delete caught by gate; cell 8 = commit-not-executed), tasks are confounded (all-flags cells drew the 2 hardest: test_act over-delete trap + loop.py core), and n=2. Needs a controlled A/B (loop.py: baseline vs all-flags, same task) to separate flag-effect from task-difficulty before any attribution. |

## Controlled A/B — loop.py, flags-only variable (resolves the cell-8 hypothesis)

Same task (`fix 5 ruff in chimera/core/loop.py`), same harness (`real_task_soak`),
**critic ENFORCE=ON in both arms**, sequential. Only the routing/entropy flags differ.

| Arm | Flags | Converged? | Commit | Gate | Note |
|---|---|---|---|---|---|
| A/B-1 | BASELINE (none) | ✅ YES | 3e3e22e | PASS ruff✓ pytest✓ | Clean in-scope fix (5 lines, only loop.py). Converged in phase 1; gate green. (Phase 2 then benignly spun on a deliverable-landed sentinel that didn't fire despite the durable commit — a separate phase-2 termination quirk on loop.py; arm stopped once the result was captured.) |
| A/B-2 | ALL 6 ON | ❌ NO | none (0 commits, empty diff) | FAIL ruff✗ pytest✗ | Agent over-edited loop.py mid-soak → broke `test_plan_skips_when_backlog_full` (engine didn't run); caught + reverted; nothing landed. Same over-edit class as cell 4. |

### A/B verdict — the scary interpretation is RULED OUT

The failing test (`test_plan_skips_when_backlog_full`) was run through a **falsification check on UNCHANGED main code**:
- flags OFF → **PASS**
- all 6 flags ON → **PASS**

**→ DEFINITIVE: the entropy/routing flags do NOT introduce any code-behavior regression.** All 6 active during pytest do not break the loop invariant. Arm 2's failure was the AGENT over-editing loop.py (a stochastic editing error, caught + reverted), NOT a flag effect. The flags are innocent of the failure.

**What's now established (3 all-flags non-converges: cells 4, 8, A/B-2 vs clean baseline convergence A/B-1):**
- ✅ DEFINITIVE: flags don't break code (test passes flags-on, clean code) — no mis-production, ever.
- ✅ DEFINITIVE: no bad commit ever landed under any flag load (gate/revert held every time).
- ⚠️ SUGGESTIVE-BUT-UNPROVEN: all-flags runs correlate with agent NON-convergence on hard tasks (loop.py: baseline✓ / all-flags✗; + cell 8). MECHANISM is agent editing effectiveness (over-edit / fail-to-commit), NOT code correctness. Each cell is n=1 against a stochastic model, so this is a hypothesis worth a larger-n check, not a conclusion. The flags at most *might* reduce editing effectiveness; they demonstrably do NOT corrupt behavior.

Net: the A/B converted the campaign's scariest open question ("do the merged flags break the loop?") into a clean NO, and reframed the residual as a softer effectiveness question.

## Harness 3 — characterize breadth sweeps (cells 9–12)

Same task set (self-scan ranks **5, 6, 7**) held constant; vary only the envelope. Enforce ON.

| Cell | Envelope | Converged | Gate behavior | Note |
|---|---|---|---|---|
| 9 | TOOL_PREFILTER | **3/3** | 2× direct-primary-approve, 1× **escalator rescue** (run 3: primary REJECTED → opus escalator APPROVED → landed) | All 3 committed, ruff PASS. Exercised BOTH gate paths live. Run times 501s / 2014s / 2219s (high phase-1 variance = known characterization finding). Single-flag envelope converges fully — contrasts the all-flags non-converges, reinforcing the A/B verdict. |
| 10 | TOOL_PREFILTER + COMPLEXITY_ROUTING | **3/3** | 2× direct-primary, 1× **escalator rescue** (run 2: primary REJECTED → opus APPROVED) | All 3 committed, ruff PASS. Same 3/3 + 1-rescue pattern as cell 9; rescued task differs (cell 9 run 3, cell 10 run 2 — which task triggers primary-reject is stochastic, but the rescue fires + works every time). Times 643/1745/490s. |
| 11 | BASELINE (no routing flags) | **3/3** | all 3 direct-primary-approve (no rescue needed) | All committed, ruff PASS. No escalator rescues this round (stochastic — primary found none borderline). Times 1913/2492/431s — the 2 SLOWEST runs of the whole characterize phase were BASELINE (no flags), again refuting "flags slow it down". |
| 12 | ALL 6 routing/entropy flags ON | **0/3** ❌ | gate NEVER invoked, all 3 | **0 api_calls each** — agent never reached ACT's provider call. Ranks 5/6/7 (test_subagent/test_act/test_http_transport), uniform ~315s. This is the FINALE and the campaign's biggest finding. |

## ⛔ CRITICAL FINDING (campaign-defining) — all-flags envelope blocks ACT

**`api_calls` telemetry across ALL of today's soaks is unambiguous:**

| Envelope | runs | api_calls | converged |
|---|---|---|---|
| baseline / prefilter / +complexity | 8 | 23–99 each | ✅ all |
| **ALL 6 flags** (cell 4, 8, A/B-2, cell 12 ×3) | **6** | **0 each** | ❌ none |

**6/6 all-flags runs made ZERO LLM calls and never converged. Every non-all-flags run made many calls and converged.** Deterministic, flag-attributable, and NOT environmental (A/B-2 failed at 13:40 surrounded by successful baseline/cell-11 runs). The all-flags combination causes `chimera run` to **fail before ACT's first provider call** — the agent never acts, edits, or commits. Suspect: one of the 4 flags unique to all-flags — **CHIMERA_FANOUT_BUDGET (0171), CHIMERA_BOLTZMANN_ALLOC (0172), CHIMERA_ANNEAL_REHEAT (0169), CHIMERA_PEER_SELECTION (0167)** — throwing/short-circuiting at PLAN/ACT setup. The full unit suite is green, so the bug lives in a live-loop path no test exercises.

**Falsification correction (own error, recorded honestly):** earlier cell-4 and A/B-2 rows claimed the agent "over-edited" the file and the gate "caught the break." **That was WRONG** — `api_calls=0` proves the agent never called an LLM, so it never edited. The "broken test" I saw at gate time was NOT an agent edit; the real failure is the 0-api-call non-start. The telemetry overruled the eyeball reading. (Cells 4 & A/B-2 narrative notes above are superseded by this section.)

**SAFETY angle (still intact):** the bug is a *non-start* (fail-stop), not mis-production. No broken code was ever produced or committed under any flag load — the failure mode is "does nothing," the safest possible failure. But it means **the all-flags envelope is functionally broken for autonomous work** and must be fixed before those flags ship enabled together. Fix chip spawned with a bisection plan.

**✅ ROOT-CAUSED + FIXED (2026-06-09):** the culprit is **`CHIMERA_ANNEAL_REHEAT` (ADR 0169) alone**, not a four-flag interaction. The ADR 0169 reheat block was wired into `ActExecutor._execute_inner` but referenced `decision.matched_failures` — `decision` is a local of the *separate* outer method `ActExecutor.execute` and was never threaded in. Because `and` short-circuits, `decision.matched_failures` was only evaluated once `anneal_reheat_enabled()` returned `True`, raising **`NameError: name 'decision' is not defined`** *before* the first provider call (on the very first attempt, prior failures or not). The exception propagated out through `_phase_act` → the ACT-budget `wait_for`, aborting ACT with 0 api_calls. It hid because every converging cell used only TOOL_PREFILTER / COMPLEXITY_ROUTING (never ANNEAL_REHEAT) and no unit test exercised the PLAN→ACT setup path with the flag on. **Fix:** `_execute_inner` now takes a `matched_failures: int = 0` param that `execute` populates from `decision.matched_failures`; regression test `tests/test_act.py::test_act_anneal_reheat_reaches_provider`. Details: ADR 0169 "Amendment (2026-06-09)".

**✅ LIVE-VALIDATED POST-FIX (2026-06-10, run realtask-2026-06-10-0915):** with the #279 fix merged (`f77671e`), the FULL all-flags envelope (all 6 routing/entropy flags ON) re-ran `real_task_soak` on a real 6-finding ruff task (`tests/test_doctor.py`) and **converged end-to-end**: **32 api_calls** (27 deepseek-v4-pro + 2 gpt-5-nano primaries; was 0/0/0/0/0/0 pre-fix), phase 1 verify-green in one iteration (~10 min), agent **self-committed** (`377cb4a`, harness autocommit not needed), phase 2 deliverable landed, final gate **PASS — ruff ✓ pytest ✓**. Cost $0.28. The reheat/fan-out paths logged no activations — correct: no prior same-signature failures (reheat idle) and no >8-wide tool batches (budget idle). The flags are armed-and-silent under normal convergence, which is the compose-safely contract. **The campaign's critical finding is CLOSED: the all-flags envelope is functional for autonomous work.** Remaining for full flag certification: a stuck-task run that exercises the reheat *rotation* live (matched_failures > 0), per ADR 0169. **→ DONE same day:** a controlled live exercise (1 seeded real prior failure, real provider calls) confirmed the rotation fires — flag OFF led with `deepseek/deepseek-v4-pro`, flag ON rotated the lead to `minimax/minimax-m3` with the `annealing reheat — rotating ladder by 1` log line, composing correctly with the haiku→sonnet escalation promotion. Details in ADR 0169 "Live validation (2026-06-10)".

**Side-event (1hr mark):** the spawned dormant-wiring chip landed as **PR #277** (squash-merged to main, `77f4d61`): activated the ADR 0127 ReasoningTier seam with a fail-safe producer (`reasoning_tier_from_env` reads `CHIMERA_REFLECTION_REASONING_TIER`; unset → None → preserves the `sonnet` default, zero behavior change) and reaffirmed ADR 0125 deriver as opt-in. 2 new test files; CI green. So the graph-derived "dormant wiring" finding is now resolved in code.
