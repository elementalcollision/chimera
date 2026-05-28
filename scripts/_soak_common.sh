# scripts/_soak_common.sh — shared safety helpers for long_cycle soak runners.
#
# Sourced by long_cycle_soak_v*.sh, long_cycle_remediation.sh, and
# long_cycle_multi_agent.sh. Two responsibilities:
#
#   1. soak_refuse_concurrent <script_basename>
#      Exits non-zero if another instance of the same script is already
#      alive. The soak v6 post-mortem (mind/postmortems/soak-v6-2026-05-22.md
#      Failure A) traced three failed launches to overlapping runners sharing
#      a hardcoded log path; this guard prevents the collision class.
#
#   2. soak_install_killgroup_trap
#      Installs an EXIT/INT/TERM trap that walks the descendant tree and
#      sends SIGTERM. Without it, `chimera run` children survive parent
#      death and keep appending to the log file orphaned.
#
# Both helpers are intentionally portable to macOS bash 3.2 (no associative
# arrays, no setsid). They depend on pgrep and pkill, which are present on
# Darwin and Linux.

soak_refuse_concurrent() {
    # Pidfile-based concurrent-instance check.
    #
    # Background: the original implementation used `pgrep -fl "$script_name"`
    # to find other running instances. This was unreliable because bash's
    # `$()` command substitution forks a SUBSHELL with the SAME argv as the
    # parent script (e.g. `bash long_cycle_soak_v34.sh`), so pgrep finds
    # itself, awk, AND the subshell — all matching the pattern. The awk
    # filter dropped self but couldn't distinguish parent-script subshells
    # from genuine concurrent instances. Diagnosed during v31 R1 daemonized
    # launch (see mind/research/v31-silent-death-postmortem-2026-05-24.md).
    #
    # Replacement: write our PID to a stable pidfile keyed on the script
    # name. On a future invocation, read the pidfile and `kill -0` the PID;
    # if alive, refuse. If dead (stale pidfile) or no pidfile, overwrite
    # and continue. The pidfile is self-healing: no explicit cleanup needed
    # on exit, because the next invocation overwrites stale entries.
    #
    # Fail-safe escape hatch: SOAK_SKIP_CONCURRENT_CHECK=1 bypasses both
    # the pidfile read and write. Useful when operator knows no other
    # instance is running (e.g. fresh reboot) or for daemonized launches
    # under non-standard process trees where the operator has already
    # verified isolation.

    local script_name="$1"

    # Escape hatch — operator can bypass entirely.
    if [ "${SOAK_SKIP_CONCURRENT_CHECK:-0}" = "1" ]; then
        return 0
    fi

    local self_pid=$$
    # $0 is the soak runner that sourced this file; it lives in scripts/.
    # The repo's state/ is a sibling.
    local repo_root
    repo_root="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || repo_root="$PWD"
    local pidfile="${repo_root}/state/soak-${script_name%.sh}.pid"
    mkdir -p "$(dirname "$pidfile")" 2>/dev/null || true

    if [ -f "$pidfile" ]; then
        local existing_pid
        existing_pid=$(cat "$pidfile" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$existing_pid" ] && [ "$existing_pid" != "$self_pid" ] \
           && kill -0 "$existing_pid" 2>/dev/null; then
            echo "FATAL: another $script_name instance is already running (PID $existing_pid):" >&2
            ps -o pid=,etime=,command= -p "$existing_pid" 2>/dev/null >&2 || true
            echo "" >&2
            echo "If you're sure no other instance is running, the pidfile is stale:" >&2
            echo "  rm $pidfile" >&2
            echo "Or to bypass this check for a single launch:" >&2
            echo "  SOAK_SKIP_CONCURRENT_CHECK=1 $0" >&2
            return 2
        fi
        # PID dead or matches self → fall through to overwrite.
    fi

    echo "$self_pid" > "$pidfile"
    return 0
}

soak_extract_sentinel_path() {
    # Parse an INBOX.md and print the first backtick-quoted
    # `mind/research/<name>.md` path. v7/v8/v9 runners were cloned
    # forward from v6 with the INBOX text updated but a sibling
    # INVESTIGATION_DOC constant left pointing at the v6 filename;
    # the runner then grep-checked the wrong file for the
    # READY-FOR-REMEDIATION sentinel and phase 1 spun forever even
    # when the agent produced the correct deliverable. Extracting
    # the target from the INBOX text removes the drift class.
    local inbox="$1"
    if [ ! -f "$inbox" ]; then
        return 1
    fi
    grep -oE '`mind/research/[A-Za-z0-9_-]+\.md`' "$inbox" \
        | head -n 1 \
        | tr -d '`'
}

soak_sync_main_from_origin() {
    # Fast-forward local `main` to `origin/main` so the soak worktree
    # branches from the freshest commit. Operator workflows
    # (chip-branch-jumps, divergent squash-merges) routinely leave local
    # main behind origin/main; the v32 post-mortem traced a DOA diff
    # (PR #61 body) to a worktree forked from a 3-commit-stale main.
    #
    # Strategy: fetch quietly (tolerate offline), checkout main, then
    # `merge --ff-only`. Refuse to clobber a diverged local main — emit
    # a WARN and let the caller proceed with the local pointer rather
    # than risk losing operator work.
    git fetch origin main --quiet 2>/dev/null || true
    git checkout main --quiet 2>&1 || return 1
    git merge --ff-only origin/main 2>&1 || {
        echo "WARN: local main diverged from origin/main; using local pointer" >&2
    }
    return 0
}

soak_reset_forward_progress() {
    # Reset the per-phase forward-progress watchdog counters. Call at the
    # top of each phase_loop so phase-1 stall state doesn't carry into
    # phase 2 (and so the grace period applies independently per phase).
    _SOAK_FP_ITER=0
    _SOAK_FP_STALL_COUNT=0
    _SOAK_FP_LAST_CYCLE=""
    _SOAK_FP_LAST_SPEND=""
    # Per-phase counters for the task-completion stall signal (ladder #6,
    # v35-postmortem attempt #4). Independent grace + threshold from the
    # (cycle, spend) signal above so they evolve separately.
    _SOAK_NC_ITER=0
    _SOAK_NC_STALL_COUNT=0
    _SOAK_NC_LOG_OFFSET=0
}

soak_extract_tasks_completed_from_log() {
    # Parse only the NEW tail of a chimera-run log (since the last call)
    # for the PR #110 ACT-budget-exceeded warning and print the most
    # recent `completed=K` integer found. The warning format is:
    #
    #   ACT phase budget exceeded: cancelled at 240s (completed=0/3 tasks)
    #
    # Defined in chimera/core/loop.py::_run_act_phase_with_budget.
    #
    # Output: integer K on stdout (most recent K in the new tail), or
    # nothing if no new ACT-budget-exceeded line appeared since last
    # call. Callers MUST treat empty as "unknown / conservative-positive"
    # (i.e. don't count as a stall). This is intentional: a missing log
    # line is ambiguous (iter still running, alternate phase, etc.) and
    # the prior call already accounted for any earlier matches.
    #
    # Uses the _SOAK_NC_LOG_OFFSET shell global (reset by
    # soak_reset_forward_progress) to remember the byte position of the
    # last scan. Safe across log rotation: if the file shrinks, the
    # offset is reset to 0.
    local log_file="$1"
    if [ ! -f "$log_file" ]; then
        return 0
    fi
    local size
    size=$(wc -c < "$log_file" 2>/dev/null | tr -d '[:space:]')
    size=${size:-0}
    local off="${_SOAK_NC_LOG_OFFSET:-0}"
    if [ "$size" -lt "$off" ]; then
        off=0
    fi
    local new_bytes=$(( size - off ))
    _SOAK_NC_LOG_OFFSET="$size"
    if [ "$new_bytes" -le 0 ]; then
        return 0
    fi
    tail -c "$new_bytes" "$log_file" 2>/dev/null \
        | grep -oE 'ACT phase budget exceeded[^(]*\(completed=[0-9]+/[0-9]+ tasks\)' \
        | awk 'END { print }' \
        | grep -oE 'completed=[0-9]+' \
        | grep -oE '[0-9]+' \
        | tail -n 1
}

soak_check_task_completion() {
    # Task-completion stall watchdog (ladder #6, v35-postmortem attempt
    # #4). Additive to soak_check_forward_progress — both signals coexist
    # and either independently triggers abort. Detects the degenerate
    # mode where every ACT phase consumes the full budget and is
    # cancelled (advancing cycle and spend) while completing ZERO tasks.
    #
    # Args:
    #   $1 = tasks-completed integer (output of
    #        soak_extract_tasks_completed_from_log); empty string means
    #        "unknown" → conservative-positive (resets stall counter).
    # Returns:
    #   0 — OK (still inside grace, K>0, or counter below threshold)
    #   1 — N consecutive K=0 iters after grace; caller MUST log FATAL
    #
    # Env knobs:
    #   SOAK_NO_COMPLETION_THRESHOLD (default 6)
    #   SOAK_NO_COMPLETION_GRACE     (default 2) — Ollama warmup buffer
    local k="$1"
    local threshold="${SOAK_NO_COMPLETION_THRESHOLD:-6}"
    local grace="${SOAK_NO_COMPLETION_GRACE:-2}"

    _SOAK_NC_ITER=$(( ${_SOAK_NC_ITER:-0} + 1 ))

    if [ "$_SOAK_NC_ITER" -le "$grace" ]; then
        _SOAK_NC_STALL_COUNT=0
        return 0
    fi

    # Empty K → conservative-positive: don't increment, don't reset.
    # Treats "unknown" as neutral rather than stall evidence.
    if [ -z "$k" ]; then
        return 0
    fi

    if [ "$k" -eq 0 ] 2>/dev/null; then
        _SOAK_NC_STALL_COUNT=$(( ${_SOAK_NC_STALL_COUNT:-0} + 1 ))
    else
        _SOAK_NC_STALL_COUNT=0
    fi

    if [ "${_SOAK_NC_STALL_COUNT:-0}" -ge "$threshold" ]; then
        return 1
    fi
    return 0
}

soak_check_forward_progress() {
    # Forward-progress watchdog (defense-in-depth at the soak harness
    # level, orthogonal to the agent loop's degenerate_loop_abort engine
    # guard). Recommended by all three v35-postmortem PRs (#102, #104,
    # #106). v35 attempt #3 spun 196 idle iterations across 1h25m before
    # the iteration cap fired — this watchdog would have aborted after
    # SOAK_NO_PROGRESS_THRESHOLD iterations of unchanged (cycle, spend).
    #
    # Args:
    #   $1 = current cycle (integer, from last_cycle_in_db)
    #   $2 = current phase spend (USD, from total_spend_in_db)
    # Returns:
    #   0 — progress OK (or still inside grace period)
    #   1 — no-progress threshold reached; caller MUST log FATAL and break
    #
    # Env knobs:
    #   SOAK_NO_PROGRESS_THRESHOLD (default 8) — consecutive stalled iters
    #   SOAK_NO_PROGRESS_GRACE     (default 3) — leading iters to skip
    #
    # Uses the _SOAK_FP_* shell globals; call soak_reset_forward_progress
    # at the top of each phase_loop to scope counters per phase.
    local cycle="$1"
    local spend="$2"
    local threshold="${SOAK_NO_PROGRESS_THRESHOLD:-8}"
    local grace="${SOAK_NO_PROGRESS_GRACE:-3}"

    _SOAK_FP_ITER=$(( ${_SOAK_FP_ITER:-0} + 1 ))

    if [ "$_SOAK_FP_ITER" -le "$grace" ]; then
        _SOAK_FP_LAST_CYCLE="$cycle"
        _SOAK_FP_LAST_SPEND="$spend"
        _SOAK_FP_STALL_COUNT=0
        return 0
    fi

    if [ "$cycle" = "${_SOAK_FP_LAST_CYCLE:-}" ] && [ "$spend" = "${_SOAK_FP_LAST_SPEND:-}" ]; then
        _SOAK_FP_STALL_COUNT=$(( ${_SOAK_FP_STALL_COUNT:-0} + 1 ))
    else
        _SOAK_FP_STALL_COUNT=0
    fi
    _SOAK_FP_LAST_CYCLE="$cycle"
    _SOAK_FP_LAST_SPEND="$spend"

    if [ "${_SOAK_FP_STALL_COUNT:-0}" -ge "$threshold" ]; then
        return 1
    fi
    return 0
}

soak_phase1_deliverable_landed() {
    # Phase-1 soft-sentinel — symmetric with soak_phase2_deliverable_landed
    # in soak_lib.sh but adapted to phase-1 semantics (engines OFF, no
    # commits expected).
    #
    # Returns 0 when ALL of:
    #   1. Every $allowed_files path exists on disk under $worktree.
    #   2. At least one of those files contains the $ready_marker line.
    #   3. The $test_cmd exits 0 from $worktree (usually `true` for
    #      research-only phase 1; the marker is the real gate).
    #
    # Closes the defect surfaced by the v36 micro-soak postmortem (PR #117):
    # the legacy phase-1 ready_marker_found exit checks INVESTIGATION_DOC
    # (the INPUT reference doc extracted from INBOX's first backticked
    # `mind/research/*.md` path) instead of the OUTPUT deliverable the
    # agent writes. v36 only converged because PR #113's task-completion
    # watchdog tripped 6 iters after the deliverable landed (inbox tasks
    # exhausted → completed=0/0 → stall counter). That alignment is
    # fragile and will not hold under v37's multi-item timing. This
    # helper gives phase 1 a documented file-presence exit path,
    # symmetric with phase 2's commit-based mechanism.
    #
    # Backward compat: callers that leave SOFT_SENTINEL_* unset for
    # phase 1 fall through to the legacy INVESTIGATION_DOC behaviour.
    local worktree="$1"
    local allowed_files="$2"
    local test_cmd="$3"
    local ready_marker="${4:-## READY-FOR-REMEDIATION}"

    if [ -z "$worktree" ] || [ -z "$allowed_files" ] || [ -z "$test_cmd" ]; then
        echo "  phase1-sentinel: bad args (need worktree, allowed_files, test_cmd)" >&2
        return 2
    fi
    if [ ! -d "$worktree" ]; then
        echo "  phase1-sentinel: $worktree is not a directory" >&2
        return 2
    fi

    local f
    for f in $allowed_files; do
        [ -f "$worktree/$f" ] || return 1
    done

    local found=0
    for f in $allowed_files; do
        if grep -qF "$ready_marker" "$worktree/$f" 2>/dev/null; then
            found=1
            break
        fi
    done
    [ "$found" -eq 1 ] || return 1

    if ! ( cd "$worktree" && bash -c "$test_cmd" ) >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

soak_install_killgroup_trap() {
    # Capture the parent PID at trap-install time so the trap function
    # uses the script's PID, not a subshell's.
    local _soak_root_pid=$$
    # shellcheck disable=SC2317
    _soak_kill_descendants() {
        local root="$1"
        # Recurse via pgrep -P (children of <root>). Post-order: kill
        # grandchildren before children so SIGTERM doesn't get lost to a
        # parent that exits and re-parents its children to init.
        local kid
        for kid in $(pgrep -P "$root" 2>/dev/null); do
            _soak_kill_descendants "$kid"
            kill -TERM "$kid" 2>/dev/null || true
        done
    }
    # shellcheck disable=SC2317
    _soak_cleanup() {
        _soak_kill_descendants "$_soak_root_pid"
    }
    trap _soak_cleanup EXIT
    trap '_soak_cleanup; exit 130' INT
    trap '_soak_cleanup; exit 143' TERM
}
