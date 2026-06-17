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
# ─────────────────────────────────────────────────────────────────────
# Process-tree helpers (memory-guard support, 2026-06-16)
# ─────────────────────────────────────────────────────────────────────
# `chimera run` spawns a subprocess tree (uv → python → its own children, plus
# any tool subprocesses like a `uv run … pytest` gate call). A runaway cycle —
# e.g. a long, non-converging ACT phase — can grow that tree until the HOST
# thrashes and crashes (observed 2026-06-16, twice). And a cleanly-exited run
# can leave orphaned grandchildren (killing the direct child does not reap a
# `uv→python→pytest` grandchild). These helpers let the watchdog measure the
# whole tree's RSS, kill the whole tree, and sweep post-exit orphans.

# Echo a root pid plus all its descendants, space-separated (BFS via pgrep -P).
_soak_proc_tree() {
    local work="$1" out="" cur kids
    while [ -n "$work" ]; do
        # shellcheck disable=SC2086  # intentional word-split of the pid worklist
        set -- $work; cur="$1"; shift; work="$*"
        out="$out $cur"
        kids="$(pgrep -P "$cur" 2>/dev/null | tr '\n' ' ')"
        work="$work $kids"
    done
    echo "$out"
}

# Sum RSS (MB) of the given pids. `ps` reports RSS in KB.
_soak_rss_mb_of() {
    [ "$#" -gt 0 ] || { echo 0; return; }
    local csv; csv="$(IFS=,; echo "$*")"
    ps -o rss= -p "$csv" 2>/dev/null | awk '{s+=$1} END{print int(s/1024)}'
}

# SIGKILL a whole process tree, descendants first (avoid re-parent races).
_soak_kill_tree() {
    local pids rev="" p
    # shellcheck disable=SC2046,SC2086
    pids="$(_soak_proc_tree "$1")"
    for p in $pids; do rev="$p $rev"; done
    for p in $rev; do kill -KILL "$p" 2>/dev/null; done
}

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
    # Memory guard (2026-06-16): cap the chimera-run PROCESS-TREE RSS. A runaway
    # cycle that would otherwise crash the host is converted into one killed
    # cycle + a log line. Tune via CHIMERA_RUN_RSS_CAP_MB (default 5000).
    local rss_cap_mb="${CHIMERA_RUN_RSS_CAP_MB:-5000}"
    local peak_rss=0 last_tree="$pid"
    echo "  watchdog: chimera run started pid=$pid (idle_timeout=${idle_timeout}s, hb=${hb_sec}s, rss_cap=${rss_cap_mb}MB)" >> "$log_file"

    while kill -0 "$pid" 2>/dev/null; do
        # Snapshot the whole tree once per poll: reused for RSS, the cap check,
        # and the post-exit orphan sweep.
        last_tree="$(_soak_proc_tree "$pid")"
        local tree_rss
        # shellcheck disable=SC2086  # intentional word-split of the pid list
        tree_rss="$(_soak_rss_mb_of $last_tree)"
        [ "$tree_rss" -gt "$peak_rss" ] && peak_rss="$tree_rss"
        if [ "$tree_rss" -gt "$rss_cap_mb" ]; then
            _soak_kill_tree "$pid"
            wait "$pid" 2>/dev/null
            echo "  watchdog: chimera run pid=$pid tree RSS ${tree_rss}MB > cap ${rss_cap_mb}MB at ${elapsed}s — KILLED TREE (memory guard); peak=${peak_rss}MB" | tee -a "$log_file"
            return 1
        fi
        if [ "$elapsed" -ge "$idle_timeout" ]; then
            _soak_kill_tree "$pid"   # tree-kill, not just $pid — no orphans
            wait "$pid" 2>/dev/null
            echo "  watchdog: chimera run pid=$pid killed after ${idle_timeout}s (silent-death guard, ADR 0120; tree-kill); peak_rss=${peak_rss}MB" | tee -a "$log_file"
            return 1
        fi
        if [ "$elapsed" -ge "$next_hb" ]; then
            echo "  watchdog heartbeat: pid=$pid alive at ${elapsed}s rss=${tree_rss}MB ($(date -u +%H:%M:%S))" >> "$log_file"
            next_hb=$((next_hb + hb_sec))
        fi
        sleep "$poll_sec"
        elapsed=$((elapsed + poll_sec))
    done

    wait "$pid" 2>/dev/null
    local rc=$?
    # Sweep orphaned grandchildren: descendants tracked on the last poll that
    # survived the run's exit (e.g. a uv→python→pytest tree from a gate call
    # whose direct child was killed but grandchildren re-parented to init).
    local p reaped=0
    for p in $last_tree; do
        [ "$p" = "$pid" ] && continue
        if kill -0 "$p" 2>/dev/null; then
            kill -KILL "$p" 2>/dev/null
            reaped=$((reaped + 1))
        fi
    done
    [ "$reaped" -gt 0 ] && echo "  watchdog: reaped ${reaped} orphaned descendant(s) after exit" >> "$log_file"
    echo "  watchdog: peak tree RSS ${peak_rss}MB" >> "$log_file"
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
    echo "soak_lib.sh v8 — v7 + watchdog process-TREE kill, RSS cap (CHIMERA_RUN_RSS_CAP_MB), peak-RSS logging, and post-exit orphan sweep (2026-06-16 memory-guard)"
}
