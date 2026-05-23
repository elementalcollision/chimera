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

    # 2. Cumulative diff touches only allowed files
    local touched
    touched="$(cd "$worktree" && git diff --name-only main..HEAD 2>/dev/null)"
    if [ -z "$touched" ]; then
        return 1
    fi
    local f
    for f in $touched; do
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
# soak_lib_version
# ─────────────────────────────────────────────────────────────────────
# Print the lib version. Runners log this so post-mortems can correlate
# soak behavior with the lib revision when the lib changes shape.
soak_lib_version() {
    echo "soak_lib.sh v1 — soft-sentinel exit (from v17+v18 retro action item #1)"
}
