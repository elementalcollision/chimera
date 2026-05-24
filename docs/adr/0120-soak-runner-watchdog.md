# ADR 0120 — Soak-runner watchdog for chimera-run liveness

**Status**: accepted
**Date**: 2026-05-23
**Companion code**: `scripts/soak_lib.sh` v3, `scripts/archive/long_cycle_soak_v23.sh`,
`chimera/core/doctor.py::_check_soak_runner_liveness`

## Context

`scripts/long_cycle_soak_vN.sh` runs `uv run chimera run` once per iteration
in a `phase_loop` helper. Through v22, the invocation was:

```bash
( cd "$WORKTREE" && uv run chimera run ) >> "$LOG" 2>&1 || {
    log "  chimera run non-zero exit (engine skips and gate denials are normal)"
}
```

The `||` branch catches non-zero exits. It does **not** catch:

- subprocess killed by external signal (OOM-killer, SIGHUP from terminal
  disconnect, parent-shell signal that doesn't propagate)
- subprocess that hangs indefinitely (network deadlock, infinite tool-call loop)

In all these cases the parent shell blocks in `wait(2)` forever. The wrapping
bg task wrapper never observes completion because the parent is still alive.
No log line, no exit code, no notification.

### Concrete failure: v22, 2026-05-23 ~20:39

`bash scripts/archive/long_cycle_soak_v22.sh` was launched in background. At
20:39:48 phase2 iter 2 began. No further log activity. At 21:00 the
chimera-run pid disappeared (`ps` empty) but the parent shell was still
blocked on `wait`. The worktree had uncommitted in-progress edits,
confirming the subprocess was mid-tool-call when killed. No task
notification fired.

The chimera-run subprocess died silently in a way that did not
propagate an exit code to the parent. Possibilities: OOM-killer
SIGKILL with no `wait()` reaper, SIGHUP from a tty hangup, an external
signal sent to the chimera-run process group but not the parent.

## Decision

Add a watchdog to `scripts/soak_lib.sh` (`soak_run_chimera_with_watchdog`)
that runs `uv run chimera run` as a backgrounded subprocess and polls
`kill -0 <pid>` every 5 seconds. If `CHIMERA_RUN_IDLE_TIMEOUT_SEC`
(default 600s = 10 min) elapses while the subprocess is still alive,
the watchdog sends SIGTERM, waits 2s, then SIGKILL, and logs a
`watchdog: chimera run pid=N killed after Ns` event.

New soak script `scripts/archive/long_cycle_soak_v23.sh` calls the watchdog
helper in place of the raw `uv run` invocation. Older scripts (v17–v22)
are NOT retrofitted — they are historical artifacts of failed soak
cycles and should not be re-launched.

Add a companion doctor check `_check_soak_runner_liveness` that scans
`state/long_cycle_v*_*.log` files: if a log's mtime is more than
`CHIMERA_DOCTOR_SOAK_LOG_STALE_MIN` (default 15) minutes old AND a
runner process of that version is still alive in `pgrep`, surface a
`warn` so the operator can intervene before the wedge propagates.

Bump `soak_lib_version()` to v3 so post-mortems can correlate behavior
with library revision.

## Consequences

**Positive**:
- A wedged chimera-run iteration costs at most `CHIMERA_RUN_IDLE_TIMEOUT_SEC`
  of wall-clock instead of blocking the soak indefinitely.
- Every termination path (clean, non-zero, watchdog kill) writes a log
  line, so post-mortems can read the full trajectory.
- Doctor surfaces stuck runners during the next routine check.

**Negative**:
- A genuinely long-running chimera iteration (>10 min) gets killed.
  Operators can raise `CHIMERA_RUN_IDLE_TIMEOUT_SEC` for soaks that
  exercise expensive tool calls.
- The watchdog uses a poll loop rather than `timeout(1)` because the
  latter is BSD-flavored on macOS with different signal semantics and
  not portable across the Mac/Linux soak hosts in use.

## Out of scope

- cgroup memory limits or supervisord-style supervision — too platform-
  specific
- Automatic iteration retry after a watchdog kill — the outer
  phase-budget loop already retries naturally
- Per-cycle budget or wall-cap changes — orthogonal
- Retrofitting v17–v22 scripts — those are historical artifacts

## Tests

- `tests/test_soak_watchdog.py::test_watchdog_fires_when_subprocess_hangs`
  — shim `uv` to `sleep 60`, watchdog timeout 3s; assert return=1 and
  total elapsed < 30s
- `test_watchdog_clean_exit_returns_zero` — shim `uv` to exit 0; assert
  no watchdog event
- `test_watchdog_nonzero_exit_returns_zero` — shim `uv` to exit 7;
  assert log records the non-zero exit; watchdog does NOT fire
- `test_soak_lib_version_is_v3` — version string mentions v3 + watchdog
