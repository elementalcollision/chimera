#!/usr/bin/env bash
# scripts/charter_build_soak.sh — GENERIC charter-build soak.
#
# Builds ANY self-authored charter (chimera charter → materialize) into a
# self-committed module, closing the originate→verify→materialize→BUILD→deliver
# loop. Where long_cycle_soak_v46.sh is hard-wired to soak_report, this is
# parameterized by CHARTER_* env vars so any materialized charter can be built.
#
# Required env:
#   CHARTER_MODULE   bare module name           (e.g. durparse)
#   CHARTER_TARGET   target source path         (e.g. chimera/durparse.py)
#   CHARTER_TEST     acceptance test path       (e.g. tests/test_durparse.py)
# Optional env:
#   CHARTER_GOAL     one-line goal for the INBOX (default: "build CHARTER_TARGET")
#   CHARTER_BASE     branch the worktree builds from (default: main). The
#                    materialized test+design must already be committed here.
#   CHARTER_DRYRUN=1 validate params, print the resolved config + phase-1 INBOX,
#                    and exit WITHOUT launching a soak (for testing / preview).
#   CHIMERA_SOAK_AUTOCOMMIT  default 1 (harness commits if the agent won't; the
#                    ADR 0148 fallback). Set 0 to require genuine self-commit.
#
# Precondition (operator): CHARTER_TEST + the design note are committed on
# CHARTER_BASE; CHARTER_TARGET does NOT yet exist (the test is red). The agent
# builds CHARTER_TARGET to green, then self-commits (phase 2).
#
# Two-phase scaffold + falsification gates + manual-handoff (NO auto-push/PR),
# identical discipline to the v46 runner; only the target is parameterized.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

# ── required params ────────────────────────────────────────────
: "${CHARTER_MODULE:?CHARTER_MODULE is required (bare module name)}"
: "${CHARTER_TARGET:?CHARTER_TARGET is required (e.g. chimera/foo.py)}"
: "${CHARTER_TEST:?CHARTER_TEST is required (e.g. tests/test_foo.py)}"
CHARTER_GOAL="${CHARTER_GOAL:-build $CHARTER_TARGET}"
CHARTER_BASE="${CHARTER_BASE:-main}"

STAMP="$(date -u +%Y-%m-%d-%H%M)"
RUN_ID="charter-${CHARTER_MODULE}-${STAMP}"
BRANCH="chimera-soak/${RUN_ID}"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-${RUN_ID}}"
GATE_TEST_CMD="uv run --extra dev pytest -q ${CHARTER_TEST}"
DELIVERABLE_REL="mind/research/${RUN_ID}-postmortem.md"

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
# Default ON: harness-commit fallback (ADR 0148). Operator captured for phase 2.
OPERATOR_SUPPRESS_PROPOSALS="${CHIMERA_SUPPRESS_PROPOSALS:-}"
CHIMERA_SOAK_AUTOCOMMIT="${CHIMERA_SOAK_AUTOCOMMIT:-1}"
export CHIMERA_SOAK_AUTOCOMMIT

READY_MARKER="## READY-FOR-REMEDIATION"
LOG="$REPO_ROOT/state/charter_build_${RUN_ID}.log"

phase1_inbox() {
    cat <<INBOX_EOF
# Inbox — charter build ${CHARTER_MODULE} phase 1 (BUILD; engines off, no commits)

**Goal**: ${CHARTER_GOAL}

Create ONE new module \`${CHARTER_TARGET}\` so the pre-written acceptance test
\`${CHARTER_TEST}\` passes. THE TEST IS THE CONTRACT — read it; do NOT edit it
(the pre-commit scope check refuses any commit that touches it). Do NOT touch any
other source file.

Run the gated test EXACTLY as written, via the shell tool with argv
["uv","run","--extra","dev","pytest","-q","${CHARTER_TEST}"]:

    ${GATE_TEST_CMD}

## Phase 1 tasks — in order
- [ ] **Build \`${CHARTER_TARGET}\` and prove green.** Read \`${CHARTER_TEST}\`
  for the EXACT contract, CREATE the module, run \`${GATE_TEST_CMD}\`, read
  failures, EDIT, RUN AGAIN until the output literally contains \`passed\` with
  zero failures. Keep imports module-level. You are NOT done until the test is
  green.
- [ ] **Write the postmortem** \`${DELIVERABLE_REL}\` (only after green) using
  \`mind/postmortems/TEMPLATE-soak-postmortem.md\`; end with the
  \`## READY-FOR-REMEDIATION\` block. Read the numbers — do NOT estimate.

SCOPE (locked): create/edit ONLY \`${CHARTER_TARGET}\` for code; write ONLY the
postmortem under mind/research/. Do NOT edit the test or any other source.
INBOX_EOF
}

if [ "${CHARTER_DRYRUN:-0}" = "1" ]; then
    echo "charter_build_soak DRYRUN"
    echo "  module    = $CHARTER_MODULE"
    echo "  target    = $CHARTER_TARGET"
    echo "  test      = $CHARTER_TEST"
    echo "  base      = $CHARTER_BASE"
    echo "  run id    = $RUN_ID"
    echo "  branch    = $BRANCH"
    echo "  gate cmd  = $GATE_TEST_CMD"
    echo "  autocommit= $CHIMERA_SOAK_AUTOCOMMIT"
    echo "--- phase-1 INBOX ---"
    phase1_inbox
    exit 0
fi

soak_refuse_concurrent "charter_build_soak.sh" || exit $?
soak_install_killgroup_trap
mkdir -p "$REPO_ROOT/state"; : > "$LOG"
START_EPOCH="$(date +%s)"
log() { local ts; ts="$(date '+%H:%M:%S')"; printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG"; }

total_spend_in_db() { sqlite3 "$1" "SELECT COALESCE(ROUND(SUM(cost_usd),4),0.0) FROM api_calls WHERE created_at >= '$2';" 2>/dev/null || echo "0.0"; }
last_cycle_in_db() { sqlite3 "$1" "SELECT COALESCE(MAX(cycle),0) FROM api_calls;" 2>/dev/null || echo "0"; }
fp_ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit (a+0 >= b+0) ? 0 : 1 }'; }

log "─────────────────────────────────────────────────────────────"
log "charter_build_soak.sh — build $CHARTER_TARGET from a self-authored charter"
log "  run id   = $RUN_ID   base = $CHARTER_BASE"
log "  gate cmd = $GATE_TEST_CMD"
log "─────────────────────────────────────────────────────────────"

if [ -e "$WORKTREE" ]; then log "FATAL: worktree exists: $WORKTREE"; exit 2; fi
git worktree add -b "$BRANCH" "$WORKTREE" "$CHARTER_BASE" 2>&1 | tee -a "$LOG"
cd "$WORKTREE" || { log "FATAL: cd worktree"; exit 2; }
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl "no-push://disabled-${RUN_ID}" 2>&1 | tee -a "$LOG" || true

if [ ! -f "$WORKTREE/$CHARTER_TEST" ]; then
    log "FATAL: $CHARTER_TEST not present on $CHARTER_BASE — materialize + commit the charter first."
    exit 2
fi

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
            local msg="[agent] build ${CHARTER_TARGET} — harness-committed (ADR 0148): agent authored+greened; runner executed the commit."
            local st; st="$(cd "$WORKTREE" && CHIMERA_V40_GATE=1 uv run python -c "
from chimera.soak_autocommit import autocommit_if_ready
print(autocommit_if_ready('.', ['${CHARTER_TARGET}', '${DELIVERABLE_REL}'], '''$msg''', test_cmd=['uv','run','--extra','dev','pytest','-q','${CHARTER_TEST}']))" 2>>"$LOG")"
            log "  harness-autocommit: ${st:-error}"
        fi
        if [ "$engines_enabled" = "1" ]; then
            if soak_phase2_deliverable_landed "$WORKTREE" "${CHARTER_TARGET} ${DELIVERABLE_REL}" "$GATE_TEST_CMD" "$CHARTER_BASE"; then
                exit_reason="soft_sentinel_deliverable_landed"; break
            fi
        else
            if soak_phase1_deliverable_landed "$WORKTREE" "$DELIVERABLE_REL" "$GATE_TEST_CMD" "$READY_MARKER"; then
                exit_reason="soft_sentinel_deliverable_landed"; break
            fi
        fi
        sleep "$COOLDOWN_SECONDS"
    done
    log "── $phase_name end: $exit_reason ──"
}

# Phase 1: build (engines off, no commits).
echo "$(phase1_inbox)" > "$WORKTREE/mind/INBOX.md"
log "phase-1 INBOX seeded ($CHARTER_TARGET)"
P1_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
phase_loop "phase1" "$PHASE1_CAP_USD" "$P1_ISO" "0"

# Phase 2: commit (engines on).
P2_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — charter build ${CHARTER_MODULE} phase 2 (commit-only, engines on)

Phase 1 built \`${CHARTER_TARGET}\` and the test passes. Commit it.

## Phase 2 tasks
- [ ] Re-run the gated test \`${GATE_TEST_CMD}\`; confirm it passes.
- [ ] Commit the deliverable in ONE step with the **\`git_commit\` tool**: call
  \`git_commit\` with message="build ${CHARTER_TARGET}" and
  paths=["${CHARTER_TARGET}", "${DELIVERABLE_REL}"]. That single tool call stages
  AND commits AND returns the new HEAD — it IS the whole commit step. The
  \`[agent]\` prefix is added for you. Do NOT stop after staging.

Manual-handoff: after the commit the runner stops with the branch in the
worktree — NO auto-push/PR/merge.
INBOX_EOF
log "phase-2 INBOX seeded"
phase_loop "phase2" "$PHASE2_CAP_USD" "$P2_ISO" "1"

log "── branch commits (expect 1 [agent] commit) ──"
( cd "$WORKTREE" && git log --oneline "$CHARTER_BASE"..HEAD ) 2>&1 | tee -a "$LOG"
log "── primary gate (post-build) ──"
( cd "$WORKTREE" && eval "$GATE_TEST_CMD" ) 2>&1 | tee -a "$LOG" || true
log "Review: cd $WORKTREE && git log --oneline $CHARTER_BASE..HEAD"
exit 0
