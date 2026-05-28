# v31 Soak Silent-Death Postmortem

**Date**: 2026-05-24
**Incident**: Soak v31 (chip-branch-jump detector, layer 1/3) bash runner
              died silently between 18:44:59 and ~18:50 EDT, ~15-20 minutes
              into a soak that was progressing normally.
**Impact**: Lost ~$0.19 of phase 1 spend; partial phase 2 progress preserved
            in worktree (design doc + uncommitted doctor.py edits); no
            production breakage; no commit reached push/PR step.
**Severity**: Medium — first observed instance of runner-level silent
              death; ADR 0120 watchdog covers subprocess hangs, NOT
              parent-bash death.

---

## Forensic Timeline (EDT)

| Time | Source | Event |
|---|---|---|
| 18:29:36 | `bsiismpfe.output` | `wiring_coordinator.sh chip-branch-jump-A` launched |
| 18:29:36 | coordinator log | `═══ launching scripts/long_cycle_soak_v31.sh ═══` |
| ~18:30 | (inferred) | Worktree created, push-block scoped, phase 1 INBOX seeded |
| 18:34:22 | soak log | `phase1 iter 2  cycle=139  spend=$0.0613` |
| 18:38:29 | mtime | `mind/research/v31-doctor-detector-design.md` written |
| 18:40:18 | soak log | `phase1 end: ready_marker_found  spend=$0.1916 iters=3` |
| 18:40:18 | soak log | `phase2 baseline ... phase-2 INBOX seeded` |
| 18:40:18 | soak log | `soft-sentinel armed: files=[chimera/core/doctor.py tests/test_doctor.py]` |
| 18:40:18 | soak log | `phase2 iter 1  cycle=140  spend=$0.0  cap=$5.00` |
| 18:40:21 | mtime | `mind/CHRONICLE.md`, `state/engines/last_runs.json` (chimera writes) |
| 18:41:30 | mtime | `chimera/core/doctor.py` modified (agent edited target file!) |
| 18:42:05 | mtime | `state/trust_state.json` (trust check ran) |
| **18:44:59** | mtime | **`state/chimera.db-wal` LAST WRITE — agent still alive** |
| (gap) | — | **No log activity, no file activity, no process activity** |
| ~18:50 | session | First operator check-in ("21min check in"); confirmed soak alive but no new log lines |
| ~19:02 | session | Second check-in; confirmed no progress past 18:40:18 |
| 19:04 | diagnostic | `ps aux | grep chimera` → no processes; coordinator gone too |

**Death window**: 18:44:59 (last filesystem activity) → no-later-than ~18:50 (when `ps` would have caught it). External kill or unhandled crash; not a hang (last write was 4m41s into iter 1, well under the 600s watchdog timeout).

---

## What Was Tried (evidence gathered)

### 1. Process state at investigation time
- `ps aux | grep -E "(chimera|long_cycle_v31)"` → **zero matches**
- Coordinator (`wiring_coordinator.sh`) and soak runner (`long_cycle_soak_v31.sh`) both gone

### 2. Harness task notification
- `bsiismpfe.output` contains ONLY the launch banner (601 bytes)
- No exit code, no halt message, no completion notification
- Compare: `bgzwnx4d0.output` (v30, clean failure) has full halt sequence

### 3. macOS unified log
- `log show` queries for kill/OOM/SIGTERM/jetsam — **empty results** (likely requires sudo for kernel subsystem events; not definitive)
- No swap usage, free RAM available — OOM unlikely

### 4. Killgroup trap definition (`scripts/_soak_common.sh`)
- `soak_install_killgroup_trap` installs `trap _soak_cleanup EXIT INT TERM`
- The cleanup walks descendant tree and `kill -TERM` everything
- **Critical**: if the trap fires, it kills all children; if the bash itself is killed with SIGKILL, the trap does NOT run

### 5. Memory + load at investigation
- 4 GB free, no swap, load avg 2.82 — system was healthy

### 6. Comparative analysis (v25-v30 vs v31)
| Soak | Wall time | Exit shape | Background task notification? |
|---|---|---|---|
| v25-v29 | 9-16 min | soft-sentinel success → coordinator auto-merge | ✓ |
| v30 | 14 min | full-suite failure → graceful halt | ✓ |
| v31 | **~15 min** | **mid-iter silent death** | **✗** |

v31's death window aligns with typical successful runtimes — **not** a runaway timeout. Death came from outside the soak's own lifecycle.

### 7. File mtimes confirm work was in progress
The agent had:
- Written the design doc in phase 1 (18:38:29)
- Started phase 2 implementation (18:41:30 edit to doctor.py)
- Run a trust check (18:42:05)
- Continued working through 18:44:59
This was NOT a stuck/hung agent — it was actively progressing when killed.

### 8. Concurrent activity check
- No other soak runners visible (`soak_refuse_concurrent` would have prevented)
- Stale `chimera-soak-v30-2026-05-24-2047` worktree exists but is idle (no processes)
- Stale `research/phase4-eval-harness` branch checked out in main worktree — evidence of an earlier chip-branch-jump papercut, NOT related to death timing

---

## Root-Cause Hypotheses (ranked)

### H1: Claude Code harness lifecycle event sent SIGTERM/SIGKILL to background task (MOST LIKELY)

**Evidence for:**
- v31 died with no graceful exit; bash EXIT trap did not log
- No notification reached the harness — consistent with the harness itself being the killer
- v25-v30 all completed within 9-16 min; v31 died at ~15 min and was working past 20 min total
- The session received a "Continue from where you left off" message at some point, consistent with harness compaction/restart
- Background bash tasks in Claude Code are tied to the harness session lifecycle; a session compaction, sleep, or restart can SIGTERM the children

**Evidence against:**
- v25-v30 ran in the same harness without dying (but their wall times were shorter)
- A SIGTERM would normally trigger the bash EXIT trap, which DOES log "── phaseN end" lines — none seen

**Refinement:** the harness may have escalated SIGTERM → SIGKILL after a grace period the trap couldn't beat (the cleanup walks the process tree and waits briefly; if the harness gives <2s before SIGKILL, the trap could be cut short before any log write completes).

### H2: macOS power-management sleep mid-soak

**Evidence for:**
- `uptime`: 12 days, 22 hrs — machine has been running long; sleep/wake cycles possible
- Sleep-while-running can SIGSTOP processes; wake can SIGCONT or kill long-orphaned

**Evidence against:**
- No log evidence (would expect sleepwake events in `log show`)
- v25-v30 ran the same morning without dying

### H3: bash error not caught by `set -uo pipefail`

**Evidence for:**
- v31's bash error handling: `set -uo pipefail` but NOT `set -e` — an error in a pipeline middle could exit without trap firing
- The script uses lots of pipelines and subshells

**Evidence against:**
- An error in the bash itself would still trigger EXIT trap (bash docs: trap fires on script exit regardless of cause)
- The script's `phase_loop` is in a `while : ; do` loop — only break statements exit it

### H4: Resource quota (max background tasks, max session runtime)

**Evidence for:**
- The harness directory has 50+ task files; bounded concurrency would explain eviction
- Possible undocumented session timeouts

**Evidence against:**
- No way to verify without harness internals

---

## ADR 0120 Gap Analysis

The watchdog (`soak_run_chimera_with_watchdog` in `scripts/soak_lib.sh`) was designed for v22's failure mode: **chimera subprocess hangs while the parent bash is alive**. It does NOT cover the v31 failure mode: **parent bash dies, subprocess dies with it**.

This is ADR 0120's open gap. The watchdog cannot watch its own parent.

## Remediation Options

### R1: Daemonize the soak (preferred)

Launch the coordinator under `nohup setsid` so it becomes its own session leader, detached from the harness's process group. SIGHUP from harness termination would no longer reach it.

```bash
# instead of:
bash scripts/wiring_coordinator.sh ...

# use:
nohup setsid bash scripts/wiring_coordinator.sh ... </dev/null >>state/coordinator.log 2>&1 &
disown
```

**Trade-off**: loses the background-task-notification integration with the harness. Operator must poll the log for completion.

### R2: Add a heartbeat file + external observer

Soak writes a `state/v31.heartbeat` file on every iter (just touch it). A separate harness-side observer process checks the mtime and surfaces a warning if the gap exceeds 2× the expected iter time. Doesn't prevent death — just makes it visible faster.

### R3: Resume capability

Add a `--resume` flag to soak runners that reads the existing chimera DB cycle state and the worktree's current INBOX, then picks up where the previous run left off. Costs: ~50 lines of bash + a state file marker indicating phase 1 vs phase 2.

### R4: Move soak runs out of the harness entirely

Use `launchctl` (macOS) or `systemd-run --user` (Linux) to schedule soaks as proper OS-level services. The harness no longer owns the lifecycle. Operator interacts via standard service tooling.

### R5: ADR 0120 Component 2 — parent-bash death detection

Have the coordinator install a UNIX socket / pidfile that any external observer can poll. If the file disappears without a corresponding "complete" log entry, alarm fires. Distinguishes graceful exit from silent death.

---

## Recommendation

**Short term (this session):**
- Adopt **R1 (daemonize via `nohup setsid`)** as a one-line change to how I launch coordinators. Validates the hypothesis (if soaks stop silently dying under nohup, H1 is confirmed).

**Medium term (1-2 chips):**
- File a chip to implement **R3 (resume)** — even with daemonization, having idempotent resumption is good hygiene.
- File a chip to add **R5 (pidfile + observer)** as ADR 0120 component 2.

**Long term:**
- Migrate to **R4 (launchctl)** once we have multiple operators or unattended cron-style soaks.

---

## Open Questions

1. Is there a documented Claude Code background-task max runtime? (Would distinguish H1 sub-hypotheses.)
2. Does session compaction actually SIGTERM background tasks? (Testable: run a long-sleeping background task, force compaction, check survival.)
3. Why did the EXIT trap not log even ONE cleanup line? (Suggests SIGKILL, not SIGTERM. Inconsistent with normal harness termination patterns.)
4. Should the coordinator install its OWN trap that writes a "killed" marker before the killgroup runs? (Would distinguish R1 vs R5 evidence next time.)

## Lessons For Next Run

- **Don't relaunch v31 in the same harness pattern blindly** — the failure mode is reproducible-by-construction.
- **The agent's phase 1 design doc is preserved** — `mind/research/v31-doctor-detector-design.md` in the worktree is good work; could be used as input to a manual finish or a daemonized re-run.
- **Coordinator log is the source of truth, NOT the harness task file** — the harness task file only captures what the coordinator's stdout produced before death.

---

**2026-05-27 archival note**: `scripts/long_cycle_soak_v31.sh` was moved to `scripts/archive/soak-runners/long_cycle_soak_v31.sh` as part of the v25–v34 soak-runner consolidation (see `mind/research/soak-runner-consolidation-2026-05-27.md`). The runner itself is unchanged; only its path moved. References above to "v31" the *incident* remain accurate; the script can be inspected at the archive path or via git history of the pre-consolidation commit.
