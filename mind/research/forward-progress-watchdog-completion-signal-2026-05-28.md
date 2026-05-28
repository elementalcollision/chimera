# Forward-progress watchdog: task-completion signal

**Date:** 2026-05-28
**Ladder:** v35-postmortem #6
**Status:** Implemented (additive to PR #109 (cycle, spend) signal)
**Companion PRs:** #109 (original watchdog), #110 (ACT-phase budget enforcement), #112 (attempt #4 postmortem)

## Motivation: the signal PR #109 misses

PR #109 added a per-iter forward-progress watchdog that tracks
`(cycle, spend)` and aborts after `SOAK_NO_PROGRESS_THRESHOLD` (default 8)
consecutive unchanged iters past a `SOAK_NO_PROGRESS_GRACE` (default 3)
grace window. It correctly catches the v35 attempt #3 mode (196 idle
iterations with no DB writes).

PR #112 (v35 soak attempt #4) exposed a *different* degenerate mode the
(cycle, spend) signal cannot see by construction:

> Every ACT phase consumes the full 240s budget cap and is cancelled,
> emitting `act_budget_exceeded` with `completed=0/N tasks`. Cycle and
> spend BOTH advance every iter (cycle from the cancellation reaching
> commit, spend from the LLM tokens consumed inside the cancelled
> phase). The (cycle, spend) watchdog stall counter resets every iter
> and can never fire.

Empirical from attempt #4: 6 consecutive iters with `completed=0/N`,
cycle and spend monotonically advancing, op-killed at iter 7. The right
signal for this mode is per-iter completed-task delta, sourced from the
PR #110 `act_budget_exceeded` warning.

## Design (LOCKED)

**Additive**, not a rename. Both signals coexist; either independently
triggers abort.

### New env knobs (only)

- `SOAK_NO_COMPLETION_THRESHOLD` (default `6`) — consecutive K=0 iters past grace
- `SOAK_NO_COMPLETION_GRACE` (default `2`) — leading iters skipped (Ollama warmup buffer)

Existing `SOAK_NO_PROGRESS_THRESHOLD` / `SOAK_NO_PROGRESS_GRACE`
**unchanged** — no rename, no repurpose, defaults preserved.

### New helpers in `scripts/_soak_common.sh`

1. `soak_extract_tasks_completed_from_log <log_file>` — reads only the
   NEW tail since the last call (byte-offset tracked in
   `_SOAK_NC_LOG_OFFSET`, reset by `soak_reset_forward_progress`),
   greps for the PR #110 warning format
   `ACT phase budget exceeded[...](completed=K/M tasks)`, prints the
   most recent K. Empty stdout on no match.

2. `soak_check_task_completion <K>` — increments a stall counter when
   K is the integer `0`; resets on K>0; **treats empty K as neutral**
   (conservative-positive: do not increment, do not reset). Skips
   counting during the grace window. Returns `1` once
   `_SOAK_NC_STALL_COUNT >= SOAK_NO_COMPLETION_THRESHOLD`.

### Distinctive abort message (verbatim)

```
FATAL: no task completion (N iterations with completed=0/M tasks at budget cap)
```

Where `N` is `SOAK_NO_COMPLETION_THRESHOLD`. Distinct from the PR #109
`FATAL: no forward progress` line so postmortem grep can attribute
cleanly.

### Call-site wiring (`scripts/long_cycle_soak_v34.sh` and `v35.sh`)

After the existing `soak_check_forward_progress` call, additive block:

```bash
local tasks_completed_k
tasks_completed_k="$(soak_extract_tasks_completed_from_log "$LOG")"
if ! soak_check_task_completion "$tasks_completed_k"; then
    log "FATAL: no task completion (${SOAK_NO_COMPLETION_THRESHOLD:-6} iterations with completed=0/M tasks at budget cap)"
    exit_reason="no_task_completion  last_k=${tasks_completed_k:-unknown}"
    break
fi
```

### Forensics

Abort path mirrors PR #109: `break` out of `phase_loop`; the worktree
is **not** deleted. State preserved for inspection.

### Backward compatibility

- Defaults preserve existing behaviour when knobs unset.
- Empty/missing log → empty K → no stall increment (cold runs and
  pre-PR-110 logs are inert).
- Both watchdog counters live on per-call shell globals; archived
  v25–v33 runners are not touched and remain unaffected.

## Counterfactual: would defaults have saved attempt #4?

**No — and this is the honest answer.**

Attempt #4 was op-killed at iter 7 after 6 consecutive `completed=0/N`
iters. With the locked defaults:

- `SOAK_NO_COMPLETION_GRACE = 2`
- `SOAK_NO_COMPLETION_THRESHOLD = 6`

The watchdog would fire at iter `grace + threshold = 2 + 6 = 8` — i.e.
**one iter after the operator already killed the run**. On attempt #4's
exact timeline this signal would not have triggered first.

It WOULD have triggered if the operator hadn't been watching: the same
pattern continuing for one more iter would have hit the threshold and
aborted with the verbatim FATAL line above, preserving the worktree for
the postmortem.

Operators who want a tighter grip can lower the threshold
(`SOAK_NO_COMPLETION_THRESHOLD=4` would fire at iter 6 on this pattern,
catching attempt #4 before operator intervention). The default of 6 is
chosen conservatively to avoid false positives on legitimate slow
phases (e.g. the first cold-Ollama embedding pass after a model swap).

The prompt's initial framing assumed `threshold=2`, but the locked
default is 6; this note records the corrected math.

## Scope honesty: defensive, not corrective

This change **does not fix agent convergence.** The attempt #4 root
cause is upstream of the soak harness: every ACT phase the agent picks
either (a) hits an infinite tool-call loop until the budget timer fires
or (b) genuinely needs >240s. PRs #110 and #112 document those failure
modes. This watchdog only **stops the bleed faster** — it caps the
wasted spend on a future stuck run from "until operator notices" to
"`(grace + threshold) * iter_cost`".

Treat this as one more chip in the defence-in-depth stack alongside
PR #109's (cycle, spend) signal and PR #110's per-phase budget cap.
The convergence work itself lives elsewhere (engine fixes, prompt
work, tool-call loop detection in `chimera/core/loop.py`).

## Test coverage

`scripts/test_soak_progress.sh` extended to 9 cases. New cases:

- **Case 5** — zero-completion stall: grace=2, threshold=3; 5 K=0 iters; abort fires at iter 5.
- **Case 6** — mixed signal: K=0, K=2, K=0, K=0 with threshold=3; counter resets on K=2; no abort.
- **Case 7** — grace=2 swallows leading K=0; stall counter still 0 after the grace window.
- **Case 8** — default behaviour preserved: 20 iters with K=3 never abort.
- **Case 9** — both signals coexist: existing (cycle, spend) signal still fires on its prior failure mode, and an empty log keeps task-completion quiet.

All 9 cases pass. Smoke test is bash-3.2 portable (Darwin + Linux).

## References

- PR #109 — original forward-progress watchdog
- PR #110 — ACT-phase budget enforcement (source of the parsed warning)
- PR #112 — v35 soak attempt #4 postmortem (motivating evidence)
- `mind/research/v35-soak-postmortem-2026-05-28-attempt4.md`
- `chimera/core/loop.py::_run_act_phase_with_budget`
