# Forward-progress watchdog for the soak loop

**Date**: 2026-05-28
**Closes**: v35-postmortem ladder recommendation #3 (final unfiled item from PRs #102, #104, #106).
**Files**: `scripts/_soak_common.sh`, `scripts/long_cycle_soak_v34.sh`, `scripts/long_cycle_soak_v35.sh`, `scripts/test_soak_progress.sh`.

## Motivation

Three consecutive v35-soak postmortems (PRs #102, #104, #106) recommended an
outer forward-progress watchdog at the soak-harness level, independent of the
agent loop's own `degenerate_loop_abort` engine guard. The recommendation went
unfiled across all three attempts. v35 attempt #3 then surfaced exactly the
failure mode the recommendation was meant to catch: **phase 1 spun 196 idle
iterations across 1h25m before the `MAX_ITERATIONS_PER_PHASE=200` cap fired.**
Cycle and spend were both pinned for the entire stretch — no useful work was
happening, and the soak burned wall time and forensics-budget for nothing.

This watchdog is defense-in-depth at the soak-harness level. It does not
replace `degenerate_loop_abort` (per-cycle, inside the agent loop) — it sits
outside that, observing the same DB the soak's spend reporter already polls,
and aborts the harness when no progress shows up over N iterations.

## Design (LOCKED)

### Helper

`soak_check_forward_progress <cycle> <spend>` in `scripts/_soak_common.sh`.

- Per-phase shell-global counters (`_SOAK_FP_*`). Reset via
  `soak_reset_forward_progress` at the top of `phase_loop` so phase-1
  state never leaks into phase 2.
- Increments a stall counter when **both** the cycle and the spend are
  unchanged from the previous iteration. Any change to either resets the
  counter to 0.
- Returns exit code 1 when the stall counter reaches the threshold; caller
  emits the FATAL log line and breaks the iteration loop.
- The killgroup trap (`soak_install_killgroup_trap`) already in place
  cleans up the chimera-run children; the worktree is preserved for
  postmortem inspection — no `git worktree remove` in the abort path.

### Env knobs

| Knob | Default | Rationale |
| --- | --- | --- |
| `SOAK_NO_PROGRESS_THRESHOLD` | `8` | At ~15s cooldown + ~10–60s per chimera-run, 8 stalled iterations is ~2–8 minutes of wall time with no progress — long enough that legitimate slow chips (Ollama embedder warmup, long-context answerer) clear it; short enough that v35 attempt #3's 196-iter stretch would have died ~25× sooner. |
| `SOAK_NO_PROGRESS_GRACE`     | `3` | First few iterations of a phase frequently include the agent reading INBOX, no DB writes yet, no spend logged. Grace=3 lets that legitimate slow start through without flapping the watchdog. |

Both numbers are heuristic, not empirical. If a future soak trips the
watchdog when it shouldn't have, the right fix is bumping the threshold
via env (`SOAK_NO_PROGRESS_THRESHOLD=16 bash scripts/long_cycle_soak_v36.sh`),
**not removing the watchdog**.

### Abort message

```
FATAL: no forward progress (N=8 iterations with cycle=42 spend=$0.3700)
── phase1 end: no_forward_progress  cycle=42  spend=$0.3700  spend=$0.3700 iters=15 ──
```

Distinctive (`FATAL: no forward progress`) so grep across soak logs cleanly
separates this exit from `max_iterations`, `max_wall_seconds`,
`phase_budget_reached`, `ready_marker_found`, and
`soft_sentinel_deliverable_landed`.

## Orthogonality from existing watchdogs

| Layer | Scope | Trigger | Survives this change |
| --- | --- | --- | --- |
| Agent-loop `degenerate_loop_abort` | per-cycle inside agent | repeated identical proposals | yes — unchanged |
| `soak_run_chimera_with_watchdog` silent-death | per-chimera-invocation | 600s no stdout | yes — unchanged |
| Phase budget (`PHASE*_CAP_USD`) | per-phase $ | spend ≥ cap − buffer | yes — unchanged |
| `MAX_ITERATIONS_PER_PHASE` | per-phase iter count | iters > 200 | yes — unchanged |
| `MAX_WALL_SECONDS` | global wall | elapsed > 14400s | yes — unchanged |
| **Forward-progress watchdog (new)** | per-phase stall | N iters with no cycle/spend delta | new |

The forward-progress check fires strictly faster than `MAX_ITERATIONS_PER_PHASE`
in the degenerate-no-progress case (8 + 3 = 11 iters vs 200). When the soak
is making real progress, it never fires; when it isn't, it stops the bleed.

## Counterfactual: what would have happened on v35 attempts #1/#2/#3

- **Attempt #1 (PR #102)**: SQLite thread-affinity defect crashed the
  persistent loop on the first cycle. Cycle never advanced past 0; spend
  never advanced past $0. After grace (3) + threshold (8) = 11 iterations
  (~3–8 min wall), watchdog would have fired with
  `FATAL: no forward progress (N=8 iterations with cycle=0 spend=$0.0000)`.
  Actual outcome: soak ran the full iteration cap before exiting.
- **Attempt #2 (PR #104)**: same crash class, same outcome.
- **Attempt #3 (PR #106)**: phase 1 stalled at the hypothesis classification
  step for 196 iterations (1h25m). Watchdog would have aborted at iter ~11.
  Saves ~1h20m of wall time + the entire phase-2 launch confusion.

## Out of scope (LOCKED)

- No Python changes.
- No CLI flags. Env knobs only.
- Archived runners under `scripts/archive/soak-runners/` (v25–v33) are not
  updated per PR #100's archive policy.
- The agent loop's `degenerate_loop_abort` engine guard is untouched.
- The silent-death watchdog in `soak_lib.sh` is untouched.
- The pidfile / concurrent-instance check is untouched.

## Smoke test

`scripts/test_soak_progress.sh` exercises four cases against the helper
in isolation (no DB, no chimera process):

1. Grace period swallows the first 3 stalled iters; trips on the 2nd post-grace stall when `THRESHOLD=2`.
2. Cycle progress resets the stall counter.
3. Spend progress also resets.
4. Defaults (`THRESHOLD=8`, `GRACE=3`) trip exactly on iter 11 (= grace + threshold).

Run with `bash scripts/test_soak_progress.sh`. Exit 0 on pass, 1 on
failure. All four cases pass in this PR.

## Honest disclosures

- This is the **fourth** recommendation from the v35-postmortem ladder
  (after PRs #102, #104, #106). The fact that it took three consecutive
  soak failures before this defensive measure landed is itself a process
  datum: "obvious-in-hindsight" defenses that get recommended but not
  filed are a real failure mode. The ladder closure is partly procedural —
  every postmortem recommendation should be filed as an explicit
  follow-up chip with an owner, not left in a freeform "future work"
  bullet at the bottom of the note.
- Threshold defaults (N=8, grace=3) are heuristic. The right operator
  response to a false-positive is `SOAK_NO_PROGRESS_THRESHOLD=<bigger>`,
  not patch-removal.
- No empirical sweep was performed to tune the threshold. We have one
  failure case (v35 attempt #3) where any threshold below ~150 would
  have helped, and zero recorded false-positives — the search space is
  hand-waved.

## References

- PR #102 — v35 attempt #1 postmortem
- PR #104 — v35 attempt #2 postmortem (relaunch)
- PR #106 — v35 attempt #3 postmortem (final)
- PR #100 — soak-runner archive policy (v25–v33 frozen)
- ADR 0141 — chip-branch-jump prevention (worktree identification)
- `chimera/engine/loop.py` — `degenerate_loop_abort` engine guard
