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
#      A single file outside the glob → NOT landed. At least ONE touched
#      file must come from the allowlist itself — mind/* journal paths are
#      auto-allowed but never sufficient (2026-06-12 campaign, Finding 2).
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
    # A1 (convergence fix): the base ref the deliverable diff is measured
    # against. Defaults to "main" (the v46 soaks build from main). The generic
    # charter-build soak builds from a CHARTER_BASE branch that ALREADY carries
    # the materialized test + design note — comparing against main would pull
    # those (un-allowlisted) files into the diff, so the sentinel never fires
    # and a clean [agent] commit falls through to no_forward_progress. Passing
    # the real base makes the diff carry only the delta the agent produced.
    local base_ref="${4:-main}"

    if [ -z "$worktree" ] || [ -z "$allowed_files" ] || [ -z "$test_cmd" ]; then
        echo "  soft-sentinel: bad args (need worktree, allowed_files, test_cmd)" >&2
        return 2
    fi
    if [ ! -d "$worktree/.git" ] && [ ! -f "$worktree/.git" ]; then
        echo "  soft-sentinel: $worktree is not a git worktree" >&2
        return 2
    fi

    # 1. At least one [agent]-prefixed commit since the base.
    local agent_commits
    agent_commits="$(cd "$worktree" && git log --format='%s' "${base_ref}..HEAD" 2>/dev/null \
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
    touched="$(cd "$worktree" && git diff --name-only "${base_ref}..HEAD" 2>/dev/null)"
    if [ -z "$touched" ]; then
        return 1
    fi
    # The journal auto-allow is permissive, not sufficient: a journal-only
    # diff means the deliverable never landed, so require at least one
    # touched path from the allowlist itself (2026-06-12 campaign,
    # Finding 2 — a journal-only [agent] commit satisfied this predicate).
    local f allowlist_hits=0
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
        allowlist_hits=$((allowlist_hits + 1))
    done
    if [ "$allowlist_hits" -eq 0 ]; then
        # Journal-only diff — no deliverable file changed
        return 1
    fi

    # 3. Test command exits 0
    if ! ( cd "$worktree" && bash -c "$test_cmd" ) >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

# ─────────────────────────────────────────────────────────────────────
# soak_phase1_verify_green  (B1 Chip 3 — real-task loop)
# ─────────────────────────────────────────────────────────────────────
#
# Phase-1 done-condition for the REAL-TASK soak, where the gate is the
# repo's OWN checks (`chimera verify`), not a pre-written charter test —
# and the deliverable is a MODIFICATION to existing files, so there is no
# `.md` ready-marker to key on (the marker-based phase-1 sentinel doesn't
# apply). The exit is purely empirical: the agent made a real, in-scope
# change AND the repo's real verification now passes.
#
# Returns 0 when ALL of:
#   1. The working tree differs from $base_ref (a real change happened) —
#      phase 1 runs engines-OFF / no-commit, so the change is uncommitted;
#      the diff is working-tree-vs-base.
#   2. Every changed path is in $allowed_files (mind/* auto-allowed, as in
#      the phase-2 sentinel) — the change stayed in scope — AND at least
#      one changed path comes from $allowed_files itself. A journal-only
#      diff is NOT a deliverable (2026-06-12 campaign, Finding 2: both
#      cells exited phase 1 "green" with zero allowlist files changed).
#   3. $gate_cmd exits 0 from the worktree — the real pipeline is green.
#      (Pass `uv run chimera verify --ruff <files> --test <target>`.)
#
# Arguments:
#   $1 = worktree path (absolute)
#   $2 = space-separated whitelist of files the change may touch
#   $3 = gate command (run via bash -c from the worktree; e.g. chimera verify)
#   $4 = base ref the diff is measured against (default: main)
#
# Returns: 0 landed · 1 not yet · 2 bad args
#
soak_phase1_verify_green() {
    local worktree="$1"
    local allowed_files="$2"
    local gate_cmd="$3"
    local base_ref="${4:-main}"

    if [ -z "$worktree" ] || [ -z "$allowed_files" ] || [ -z "$gate_cmd" ]; then
        echo "  phase1-verify: bad args (need worktree, allowed_files, gate_cmd)" >&2
        return 2
    fi
    if [ ! -d "$worktree/.git" ] && [ ! -f "$worktree/.git" ]; then
        echo "  phase1-verify: $worktree is not a git worktree" >&2
        return 2
    fi

    # 1. A real change exists (working tree vs base) — tracked-file edits.
    local touched
    touched="$(cd "$worktree" && git diff --name-only "$base_ref" 2>/dev/null)"
    if [ -z "$touched" ]; then
        return 1
    fi

    # 2. Every changed file is in scope (mind/* auto-allowed; see ADR 0121),
    # and at least one is from the allowlist itself — the journal auto-allow
    # must not satisfy the predicate alone (2026-06-12 campaign, Finding 2).
    local f allowlist_hits=0
    for f in $touched; do
        case "$f" in
            mind/*) continue ;;
        esac
        local ok=0 allowed
        for allowed in $allowed_files; do
            if [ "$f" = "$allowed" ]; then ok=1; break; fi
        done
        if [ "$ok" -eq 0 ]; then
            return 1
        fi
        allowlist_hits=$((allowlist_hits + 1))
    done
    if [ "$allowlist_hits" -eq 0 ]; then
        # Journal-only diff — no deliverable file changed
        return 1
    fi

    # 3. The repo's real verification passes.
    if ! ( cd "$worktree" && bash -c "$gate_cmd" ) >/dev/null 2>&1; then
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

    # Diagnostics chip: a long agent cycle (e.g. a slow LLM call) writes nothing
    # to the log for tens of seconds, which is indistinguishable from a dead
    # process when an observer can't see the process table (sandboxed `ps`).
    # Emit a timestamped HEARTBEAT each poll so liveness is unambiguous from the
    # log alone — and decode the EXIT cause (clean rc vs killed-by-signal) so an
    # external reap (SIGHUP/SIGTERM/SIGKILL) is distinguishable from a normal
    # non-zero exit. ``CHIMERA_RUN_HEARTBEAT_SEC`` (default 15) controls cadence.
    ( cd "$worktree" && uv run chimera run ) >> "$log_file" 2>&1 &
    local pid=$!
    local elapsed=0
    local poll_sec=5
    local hb_sec="${CHIMERA_RUN_HEARTBEAT_SEC:-15}"
    local next_hb="$hb_sec"
    echo "  watchdog: chimera run started pid=$pid (idle_timeout=${idle_timeout}s, hb=${hb_sec}s)" >> "$log_file"

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
        if [ "$elapsed" -ge "$next_hb" ]; then
            echo "  watchdog heartbeat: pid=$pid alive at ${elapsed}s ($(date -u +%H:%M:%S))" >> "$log_file"
            next_hb=$((next_hb + hb_sec))
        fi
        sleep "$poll_sec"
        elapsed=$((elapsed + poll_sec))
    done

    wait "$pid" 2>/dev/null
    local rc=$?
    if [ "$rc" -gt 128 ]; then
        local sig=$((rc - 128))
        local nm="SIG${sig}"
        case "$sig" in 1) nm="SIGHUP";; 2) nm="SIGINT";; 9) nm="SIGKILL";;
            15) nm="SIGTERM";; esac
        echo "  watchdog: chimera run pid=$pid KILLED BY SIGNAL ${sig} (${nm}) at ${elapsed}s — external reap, NOT a clean exit" >> "$log_file"
    elif [ "$rc" -ne 0 ]; then
        echo "  watchdog: chimera run exited rc=$rc at ${elapsed}s (engine skips and gate denials are normal)" >> "$log_file"
    else
        echo "  watchdog: chimera run exited cleanly (rc=0) at ${elapsed}s" >> "$log_file"
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# soak_lib_version
# ─────────────────────────────────────────────────────────────────────
# Print the lib version. Runners log this so post-mortems can correlate
# soak behavior with the lib revision when the lib changes shape.
soak_lib_version() {
    echo "soak_lib.sh v7 — sentinels require >=1 allowlist path (mind/* journal auto-allow is permissive, not sufficient; 2026-06-12 Finding 2); watchdog heartbeat + signal-decoded exit"
}
