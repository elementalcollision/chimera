# scripts/soak_lib.sh — shared helpers for long_cycle_soak_v*.sh runners
#
# Source from a soak runner with:
#   source "$(dirname "$0")/soak_lib.sh"
#
# Contract: helpers operate on a $WORKTREE that is a git worktree on
# a chimera-soak/* branch forked from main. They are read-only against
# the worktree state (no commits, no pushes); the caller decides what
# to do with the return value.

# ─────────────────────────────────────────────────────────────────────
# soak_phase2_deliverable_landed
# ─────────────────────────────────────────────────────────────────────
#
# Returns 0 (success) when phase 2 has produced a charter-clean,
# test-green deliverable that the runner can exit on early — implementing
# the "soft sentinel" from the v17+v18 retrospective.
#
# A deliverable counts as landed when ALL of:
#   1. There is at least one [agent]-prefixed commit on the soak branch
#      since main.
#   2. The cumulative diff of those agent commits against main touches
#      ONLY files matching the passed-in charter_glob (a bash extended
#      glob, e.g. "chimera/core/escalation.py tests/test_task_escalation.py").
#      A single file outside the glob → NOT landed.
#   3. The passed-in test_cmd exits 0 when run from $WORKTREE.
#
# When all three are true, the runner can `break` out of the phase-2
# loop without waiting for the budget cap. This saves ~80% of spend on
# the post-deliverable iter-3 tail where v18 burned $0.40 on diffs the
# witness panel rejected anyway.
#
# Usage in a phase_loop:
#   if soak_phase2_deliverable_landed \
#        "$WORKTREE" \
#        "chimera/core/escalation.py tests/test_task_escalation.py" \
#        "uv run pytest tests/test_task_escalation.py -q"; then
#       exit_reason="soft_sentinel_deliverable_landed"; break
#   fi
#
# Arguments:
#   $1 = worktree path (absolute)
#   $2 = space-separated whitelist of files the diff is allowed to touch
#        (must be relative to the worktree root, exact paths — no globs;
#        keeping it strict-match means a wildcard charter would have to
#        be enumerated explicitly, which is the desired behavior for soak)
#   $3 = test command (run via bash -c from the worktree)
#
# Returns:
#   0  → deliverable landed; runner should exit phase 2
#   1  → not yet; runner should continue
#   2  → error (bad args)
#
soak_phase2_deliverable_landed() {
    local worktree="$1"
    local allowed_files="$2"
    local test_cmd="$3"

    if [ -z "$worktree" ] || [ -z "$allowed_files" ] || [ -z "$test_cmd" ]; then
        echo "  soft-sentinel: bad args (need worktree, allowed_files, test_cmd)" >&2
        return 2
    fi
    if [ ! -d "$worktree/.git" ] && [ ! -f "$worktree/.git" ]; then
        echo "  soft-sentinel: $worktree is not a git worktree" >&2
        return 2
    fi

    # 1. At least one [agent]-prefixed commit since main
    local agent_commits
    agent_commits="$(cd "$worktree" && git log --format='%s' main..HEAD 2>/dev/null \
                      | grep -c '^\[agent\]')"
    if [ "${agent_commits:-0}" -lt 1 ]; then
        return 1
    fi

    # 2. Cumulative diff touches only allowed files.
    # Convention (v19 retro → v25 expansion): any path under mind/
    # is auto-allowed. The mind/ tree is operational state the
    # chimera-run loop writes between cycles (CHRONICLE, HEARTBEAT,
    # INBOX, SESSION_LOG, research design + remediation docs, wiki) —
    # none of it is source code under test. Across soaks v19–v25 the
    # agent reliably co-stages journal updates with the deliverable;
    # charter strengthening did not overcome the behavior. Allowing
    # mind/* in the soft-sentinel diff is faithful to the contract's
    # intent (the deliverable shipped cleanly under the charter's
    # source-file scope). See ADR 0121.
    local touched
    touched="$(cd "$worktree" && git diff --name-only main..HEAD 2>/dev/null)"
    if [ -z "$touched" ]; then
        return 1
    fi
    local f
    for f in $touched; do
        # Auto-allow operational journal artifacts under mind/
        case "$f" in
            mind/*) continue ;;
        esac
        local ok=0
        local allowed
        for allowed in $allowed_files; do
            if [ "$f" = "$allowed" ]; then ok=1; break; fi
        done
        if [ "$ok" -eq 0 ]; then
            # Out-of-charter file present — deliverable is NOT clean
            return 1
        fi
    done

    # 3. Test command exits 0
    if ! ( cd "$worktree" && bash -c "$test_cmd" ) >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

# ─────────────────────────────────────────────────────────────────────
# soak_run_chimera_with_watchdog
# ─────────────────────────────────────────────────────────────────────
#
# Run `uv run chimera run` in $WORKTREE with a watchdog that kills the
# subprocess if it exceeds $idle_timeout seconds. v22 post-mortem
# (ADR 0120) found a chimera-run subprocess died silently mid-tool-call
# (no exit-code propagation, no log line) and the parent shell blocked
# forever waiting for a reaper that never arrived.
#
# Arguments:
#   $1 = worktree path (absolute, must contain pyproject.toml)
#   $2 = log file path (absolute, appended to)
#   $3 = idle timeout seconds (optional, default 600 = 10 min, or
#        the env var CHIMERA_RUN_IDLE_TIMEOUT_SEC if set)
#
# Echoes a single status line to stdout AND $log:
#   ok       — clean exit
#   nonzero  — non-zero exit (engine skips and gate denials are normal)
#   watchdog — timeout fired, subprocess SIGTERM'd
#
# Returns:
#   0  → clean exit OR non-zero (caller treats both as "iteration ran")
#   1  → watchdog fired (caller may want to count this as an iter fail)
#
# Implementation note: uses a backgrounded subprocess + polling loop
# rather than `timeout(1)` because the latter is BSD-flavored on macOS
# (signal semantics differ) and not guaranteed installed.
#
soak_run_chimera_with_watchdog() {
    local worktree="$1"
    local log_file="$2"
    local idle_timeout="${3:-${CHIMERA_RUN_IDLE_TIMEOUT_SEC:-600}}"

    if [ -z "$worktree" ] || [ -z "$log_file" ]; then
        echo "  watchdog: bad args (need worktree, log_file)" >&2
        return 2
    fi

    ( cd "$worktree" && uv run chimera run ) >> "$log_file" 2>&1 &
    local pid=$!
    local elapsed=0
    local poll_sec=5

    while kill -0 "$pid" 2>/dev/null; do
        if [ "$elapsed" -ge "$idle_timeout" ]; then
            kill -TERM "$pid" 2>/dev/null
            sleep 2
            kill -KILL "$pid" 2>/dev/null  # belt+suspenders if SIGTERM ignored
            wait "$pid" 2>/dev/null
            local msg="  watchdog: chimera run pid=$pid killed after ${idle_timeout}s (silent-death guard, ADR 0120)"
            echo "$msg" | tee -a "$log_file"
            return 1
        fi
        sleep "$poll_sec"
        elapsed=$((elapsed + poll_sec))
    done

    wait "$pid" 2>/dev/null
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  chimera run non-zero exit ($rc) (engine skips and gate denials are normal)" >> "$log_file"
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# soak_lib_version
# ─────────────────────────────────────────────────────────────────────
# Print the lib version. Runners log this so post-mortems can correlate
# soak behavior with the lib revision when the lib changes shape.
soak_lib_version() {
    echo "soak_lib.sh v4 — mind/* journal auto-allow (structural fix for journal-pollution blocker, observed v19-v25)"
}
