#!/usr/bin/env bash
# scripts/real_task_soak.sh — REAL-TASK soak (B1 Chip 3, ADR 0158).
#
# The first production-value loop: drive Chimera to make + fix a GENUINE
# maintenance change (a real failing test, a dep bump, a small refactor) and
# verify it against the repo's OWN checks — `chimera verify` (real ruff +
# pytest) — NOT a pre-written charter test. "Makes the codebase better," not
# "passes the test we gave it." The agent iterates against the real pipeline's
# actual failure output; a human reviews the resulting PR.
#
# This is charter_build_soak's sibling: same two-phase scaffold, falsification
# gates, and manual-handoff discipline — but the gate is `chimera verify` and
# the deliverable is a modification to EXISTING files (not a new module), so
# phase 1 exits on soak_phase1_verify_green (a real in-scope diff + green gate)
# rather than a `.md` ready-marker.
#
# Required env:
#   TASK_GOAL    one-line description of the maintenance task (for the INBOX)
#   TASK_FILES   space-separated allowlist of files the change may touch
#                (exact paths, relative to repo root) — also the ruff scope
# Optional env:
#   TASK_TEST    pytest target to narrow the gate to (e.g. tests/test_x.py or
#                tests/test_x.py::test_y). Omit to run the FULL suite (slow).
#   TASK_BASE    branch the worktree builds from (default: main)
#   TASK_DRYRUN=1  validate params, print the resolved config + phase-1 INBOX,
#                  and exit WITHOUT launching a soak (for testing / preview).
#   CHIMERA_SOAK_AUTOCOMMIT  default 1 (harness commits if the agent won't; the
#                  ADR 0148 fallback). Set 0 to require genuine self-commit.
#
# Precondition (operator): the task is real and low-risk; TASK_FILES enumerates
# exactly the files a correct change touches; if the task is "fix a failing
# test", that test is already red on TASK_BASE.
#
# Manual-handoff: the runner stops with the branch in the worktree — NO
# auto-push/PR/merge. The operator reviews and opens the PR.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

# ── required params ────────────────────────────────────────────
: "${TASK_GOAL:?TASK_GOAL is required (one-line task description)}"
: "${TASK_FILES:?TASK_FILES is required (space-separated allowlist of paths)}"
TASK_TEST="${TASK_TEST:-}"
TASK_BASE="${TASK_BASE:-main}"

STAMP="$(date -u +%Y-%m-%d-%H%M)"
RUN_ID="realtask-${STAMP}"
BRANCH="chimera-soak/${RUN_ID}"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-${RUN_ID}}"

# The gate IS the repo's real verification, narrowed to the change.
GATE_RUFF=""
for f in $TASK_FILES; do GATE_RUFF="$GATE_RUFF --ruff $f"; done
GATE_TEST_ARG=""
[ -n "$TASK_TEST" ] && GATE_TEST_ARG="--test $TASK_TEST"
# shellcheck disable=SC2086
GATE_VERIFY_CMD="uv run chimera verify${GATE_RUFF} ${GATE_TEST_ARG}"

PHASE1_CAP_USD="${PHASE1_CAP_USD:-2.50}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.25}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-7200}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_V40_GATE=1
export CHIMERA_SOAK_RUN_ID="$RUN_ID"
export CHIMERA_ACT_BUDGET_SECONDS="${CHIMERA_ACT_BUDGET_SECONDS:-600}"
OPERATOR_SUPPRESS_PROPOSALS="${CHIMERA_SUPPRESS_PROPOSALS:-}"
CHIMERA_SOAK_AUTOCOMMIT="${CHIMERA_SOAK_AUTOCOMMIT:-1}"
export CHIMERA_SOAK_AUTOCOMMIT

LOG="$REPO_ROOT/state/real_task_${RUN_ID}.log"

phase1_inbox() {
    cat <<INBOX_EOF
# Inbox — real-task soak phase 1 (FIX; engines off, no commits)

**Task**: ${TASK_GOAL}

Make the change that satisfies the task, then prove it against the repo's REAL
checks. The gate is the project's OWN verification — ruff + pytest — NOT a test
written for you. Run it yourself and read the actual failure output:

\`\`\`
${GATE_VERIFY_CMD}
\`\`\`

Iterate edit → \`chimera verify\` → read failures → fix, until it prints
\`PASS\`. The structured failure detail on stderr is your signal.

## Phase 1 tasks
- [ ] **Make the change and prove \`chimera verify\` is green.** Edit ONLY the
  files in SCOPE below. Run \`${GATE_VERIFY_CMD}\` and keep fixing until it
  exits 0 (\`PASS\`).
- [ ] Do NOT commit in phase 1 (engines are off). The runner commits in phase 2.

SCOPE (locked): edit ONLY these files for the fix — ${TASK_FILES}. Operational
journal notes under mind/ are allowed. Anything else is out of scope.
INBOX_EOF
}

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    echo "=== real_task_soak.sh config (dryrun) ==="
    echo "  goal      = $TASK_GOAL"
    echo "  files     = $TASK_FILES"
    echo "  test      = ${TASK_TEST:-<full suite>}"
    echo "  base      = $TASK_BASE"
    echo "  run id    = $RUN_ID"
    echo "  gate cmd  = $GATE_VERIFY_CMD"
    echo "  autocommit= $CHIMERA_SOAK_AUTOCOMMIT"
    echo "  worktree  = $WORKTREE"
    echo "--- phase-1 INBOX ---"
    phase1_inbox
    exit 0
fi

mkdir -p "$REPO_ROOT/state"
START_EPOCH="$(date +%s)"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "real_task_soak.sh — $TASK_GOAL"
log "  run id   = $RUN_ID   base = $TASK_BASE"
log "  gate cmd = $GATE_VERIFY_CMD"
log "─────────────────────────────────────────────────────────────"

if [ -e "$WORKTREE" ]; then log "FATAL: worktree exists: $WORKTREE"; exit 2; fi
git worktree add -b "$BRANCH" "$WORKTREE" "$TASK_BASE" 2>&1 | tee -a "$LOG"
cd "$WORKTREE" || { log "FATAL: cd worktree"; exit 2; }
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl "no-push://disabled-${RUN_ID}" 2>&1 | tee -a "$LOG" || true

WORKTREE_STATE="$WORKTREE/state"; WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"
[ -f "$REPO_ROOT/state/trust_state.json" ] && cp "$REPO_ROOT/state/trust_state.json" "$WORKTREE_STATE/"
export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"
mkdir -p "$WORKTREE/mind/research"

source "$(dirname "$0")/../scripts/soak_lib.sh" 2>/dev/null || source "$REPO_ROOT/scripts/soak_lib.sh"
log "$(soak_lib_version)"

phase_loop() {
    local phase_name="$1" cap_usd="$2" phase_start_iso="$3" engines_enabled="$4"
    local cap_minus_buffer; cap_minus_buffer="$(awk -v c="$cap_usd" -v b="$SAFETY_BUFFER_USD" 'BEGIN { print c - b }')"
    export CHIMERA_ENGINES_ENABLED="$engines_enabled"
    if [ "$engines_enabled" = "1" ]; then
        export CHIMERA_SUPPRESS_PROPOSALS="${OPERATOR_SUPPRESS_PROPOSALS:-1}"
    else
        unset CHIMERA_SUPPRESS_PROPOSALS
    fi
    local iter=0 exit_reason=""
    soak_reset_forward_progress
    log "── $phase_name start: cap=\$$cap_usd engines=$engines_enabled ──"
    while : ; do
        iter=$((iter+1))
        [ "$iter" -gt "$MAX_ITERATIONS_PER_PHASE" ] && { exit_reason="max_iterations"; break; }
        local now; now="$(date +%s)"
        [ $((now - START_EPOCH)) -ge "$MAX_WALL_SECONDS" ] && { exit_reason="max_wall_seconds"; break; }
        local spend; spend="$(total_spend_in_db "$WORKTREE_DB" "$phase_start_iso")"
        fp_ge "$spend" "$cap_minus_buffer" && { exit_reason="phase_budget_reached spend=\$$spend"; break; }
        local cycle_pre; cycle_pre="$(last_cycle_in_db "$WORKTREE_DB")"
        if ! soak_check_forward_progress "$cycle_pre" "$spend"; then exit_reason="no_forward_progress cycle=$cycle_pre"; break; fi
        log "$phase_name iter $iter  cycle=$cycle_pre  spend=\$$spend  cap=\$$cap_usd"
        soak_run_chimera_with_watchdog "$WORKTREE" "$LOG" || log "  watchdog fired ($phase_name iter $iter)"
        if [ "$engines_enabled" = "1" ] && [ "$CHIMERA_SOAK_AUTOCOMMIT" = "1" ]; then
            local msg="[agent] ${TASK_GOAL} — harness-committed (ADR 0148): agent authored+verified; runner executed the commit."
            local files_py="["; local first=1
            for f in $TASK_FILES; do
                [ "$first" = "1" ] && first=0 || files_py="$files_py, "
                files_py="$files_py'$f'"
            done
            files_py="$files_py]"
            local st; st="$(cd "$WORKTREE" && CHIMERA_V40_GATE=1 uv run python -c "
from chimera.soak_autocommit import autocommit_if_ready
print(autocommit_if_ready('.', ${files_py}, '''$msg''', test_cmd=['bash','-c','''${GATE_VERIFY_CMD}''']))" 2>>"$LOG")"
            log "  harness-autocommit: ${st:-error}"
        fi
        if [ "$engines_enabled" = "1" ]; then
            if soak_phase2_deliverable_landed "$WORKTREE" "$TASK_FILES" "$GATE_VERIFY_CMD" "$TASK_BASE"; then
                exit_reason="soft_sentinel_deliverable_landed"; break
            fi
        else
            if soak_phase1_verify_green "$WORKTREE" "$TASK_FILES" "$GATE_VERIFY_CMD" "$TASK_BASE"; then
                exit_reason="soft_sentinel_verify_green"; break
            fi
        fi
        sleep "$COOLDOWN_SECONDS"
    done
    log "── $phase_name end: $exit_reason ──"
}

# Phase 1: fix (engines off, no commits).
echo "$(phase1_inbox)" > "$WORKTREE/mind/INBOX.md"
log "phase-1 INBOX seeded ($TASK_GOAL)"
P1_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
phase_loop "phase1" "$PHASE1_CAP_USD" "$P1_ISO" "0"

# Phase 2: commit (engines on).
P2_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — real-task soak phase 2 (commit-only, engines on)

Phase 1 made the change and \`chimera verify\` passes. Commit it.

## Phase 2 tasks
- [ ] Re-run the gate \`${GATE_VERIFY_CMD}\`; confirm it prints \`PASS\`.
- [ ] Commit the change in ONE step with the **\`git_commit\` tool**: call
  \`git_commit\` with message="${TASK_GOAL}" and paths=[${TASK_FILES}]. That
  single tool call stages AND commits AND returns the new HEAD — it IS the whole
  commit step. The \`[agent]\` prefix is added for you. Do NOT stop after staging.

Manual-handoff: after the commit the runner stops with the branch in the
worktree — NO auto-push/PR/merge.
INBOX_EOF
log "phase-2 INBOX seeded"
phase_loop "phase2" "$PHASE2_CAP_USD" "$P2_ISO" "1"

log "── branch commits (expect 1 [agent] commit) ──"
( cd "$WORKTREE" && git log --oneline "$TASK_BASE"..HEAD ) 2>&1 | tee -a "$LOG"
log "── gate (post-fix) ──"
( cd "$WORKTREE" && eval "$GATE_VERIFY_CMD" ) 2>&1 | tee -a "$LOG" || true
log "Review: cd $WORKTREE && git log --oneline $TASK_BASE..HEAD"
exit 0
