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
