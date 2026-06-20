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
#
# ── Multi-repo (ADR 0186 B.2) ──────────────────────────────────────────
# When TASK_REPO ("owner/name") AND TASK_VERIFY_CMD are set, the runner soaks
# a FOREIGN target repo instead of the chimera self-repo:
#   TASK_REPO        owner/name of the foreign target repo (e.g.
#                    elementalcollision/claude-daemon). MUST match
#                    CHIMERA_REPO_ALLOWLIST (fail-closed otherwise).
#   TASK_VERIFY_CMD  the foreign repo's OWN gate command — pytest / npm test /
#                    cargo test / … — `chimera verify` cannot express it, so it
#                    becomes GATE_VERIFY_CMD against the foreign checkout.
#   CHIMERA_REPO_ALLOWLIST  space/comma-separated allowlist of "owner" or
#                    "owner/name" entries (default: the single owner
#                    `elementalcollision`). A non-allowlisted TASK_REPO is
#                    REFUSED before any clone or agent action (fail-closed).
# In foreign mode the runner clones the target into a managed workspace dir,
# points REPO_ROOT/WORKTREE/gate at that checkout, sets FAITH_CMD/REVIEW_CMD
# empty (they assume the chimera codebase), and stays draft-PR-only /
# manual-handoff — NO cross-repo push, NO auto-merge. self_pr generalization to
# foreign remotes is OUT OF SCOPE for B.2 (see the foreign self-PR TODO below).
#
# HARD CONSTRAINT: when TASK_REPO is UNSET the behaviour is byte-identical to
# the self-repo path the live daily loop depends on — every foreign-mode line is
# gated behind a `[ -n "${TASK_REPO:-}" ]` check and never runs in self-mode.

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
# RUN_ID_SUFFIX disambiguates back-to-back runs of the SAME minute (e.g.
# ab_soak.sh's two model arms) so their branches, worktrees, and ledger run_ids
# never collide — and the arm stays legible in the [soak-outcome] run_id. Unset
# → identical to the original `realtask-<stamp>`.
RUN_ID="realtask-${STAMP}${RUN_ID_SUFFIX:+-${RUN_ID_SUFFIX}}"
BRANCH="chimera-soak/${RUN_ID}"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-${RUN_ID}}"

# The gate IS the repo's real verification, narrowed to the change.
GATE_RUFF=""
for f in $TASK_FILES; do GATE_RUFF="$GATE_RUFF --ruff $f"; done
GATE_TEST_ARG=""
[ -n "$TASK_TEST" ] && GATE_TEST_ARG="--test $TASK_TEST"
# shellcheck disable=SC2086
GATE_VERIFY_CMD="uv run chimera verify${GATE_RUFF} ${GATE_TEST_ARG}"

# Faithfulness check (ADR 0159): mutation teeth + differential-vs-base over the
# FIRST changed file. Toward no-contract verification — the agent must not pass
# the suite by leaving behaviour unpinned or silently deleting untested branches.
# Only meaningful with a TASK_TEST; targets one file (single-file maintenance).
# Faithfulness + critic cover EVERY changed file (multi-file changes are
# faithful only if all files are). Build --target args over all TASK_FILES.
TARGET_ARGS=""
for f in $TASK_FILES; do TARGET_ARGS="$TARGET_ARGS --target $f"; done
FAITH_CMD=""
# shellcheck disable=SC2086
[ -n "$TASK_TEST" ] && FAITH_CMD="uv run chimera faithfulness${TARGET_ARGS} --test ${TASK_TEST} --base ${TASK_BASE}"
# Cross-model critic (ADR 0160): adjudicates faithfulness across all files before
# the commit — the judgment the gates can't make. Advisory in-loop (fail-closed),
# surfaced so the agent addresses concerns; the operator sees the verdict.
# shellcheck disable=SC2086
REVIEW_CMD="uv run chimera review${TARGET_ARGS} --base ${TASK_BASE} --goal \"${TASK_GOAL}\""
[ -n "$TASK_TEST" ] && REVIEW_CMD="${REVIEW_CMD} --test ${TASK_TEST}"

# ── Multi-repo foreign-target overrides (ADR 0186 B.2) ─────────────────
# EVERYTHING in this block runs ONLY when TASK_REPO is set. When TASK_REPO is
# unset the block is skipped entirely and REPO_ROOT/WORKTREE/GATE_VERIFY_CMD/
# FAITH_CMD/REVIEW_CMD keep the self-repo values computed above — so the
# self-repo path is byte-identical to pre-0186.
TASK_REPO="${TASK_REPO:-}"
FOREIGN_MODE=0
FOREIGN_CLONE_TARGET=""
FOREIGN_ALLOW_DECISION=""
if [ -n "$TASK_REPO" ]; then
    FOREIGN_MODE=1
    TASK_VERIFY_CMD="${TASK_VERIFY_CMD:-}"
    # A foreign repo MUST supply its own gate (chimera verify can't express it).
    : "${TASK_VERIFY_CMD:?TASK_VERIFY_CMD is required when TASK_REPO is set (the foreign repo own gate: pytest/npm/cargo)}"

    # ALLOWLIST — fail-closed BEFORE any clone or agent action (B.4 safety).
    # CHIMERA_REPO_ALLOWLIST is space/comma-separated; an entry is either a bare
    # owner ("elementalcollision" → any repo under it) or a full "owner/name".
    # Default: the single owner elementalcollision.
    CHIMERA_REPO_ALLOWLIST="${CHIMERA_REPO_ALLOWLIST:-elementalcollision}"
    _repo_owner="${TASK_REPO%%/*}"
    _allow_ok=0
    for _entry in $(echo "$CHIMERA_REPO_ALLOWLIST" | tr ',' ' '); do
        [ -z "$_entry" ] && continue
        if [ "$_entry" = "$TASK_REPO" ] || [ "$_entry" = "$_repo_owner" ]; then
            _allow_ok=1
            break
        fi
    done
    if [ "$_allow_ok" = "1" ]; then
        FOREIGN_ALLOW_DECISION="ALLOWED (matches '$CHIMERA_REPO_ALLOWLIST')"
    else
        FOREIGN_ALLOW_DECISION="REFUSED (not in '$CHIMERA_REPO_ALLOWLIST')"
        echo "FATAL: TASK_REPO '$TASK_REPO' is not in CHIMERA_REPO_ALLOWLIST ('$CHIMERA_REPO_ALLOWLIST')." >&2
        echo "       Refusing to clone or act on a non-allowlisted repo (ADR 0186 B.4 fail-closed)." >&2
        echo "       Allow it with: CHIMERA_REPO_ALLOWLIST='$TASK_REPO' (or its owner)." >&2
        exit 3
    fi

    # Managed workspace for the foreign checkout — a sibling of REPO_ROOT so it
    # never lands inside the chimera worktree. <sanitized-repo>-<runid> keeps
    # back-to-back runs isolated.
    _repo_sanitized="$(echo "$TASK_REPO" | tr '/' '-' | tr -cd 'A-Za-z0-9._-')"
    FOREIGN_CLONE_TARGET="$REPO_ROOT/../chimera-foreign-${_repo_sanitized}-${RUN_ID}"

    # RUNNER_ROOT is the chimera self-checkout (where soak_lib.sh, the log, and
    # the runner's own state live). In foreign mode REPO_ROOT/WORKTREE move to
    # the target clone, but the runner still sources its libs + writes its log
    # from RUNNER_ROOT. (In self mode this whole block is skipped and the
    # original lines run untouched.)
    RUNNER_ROOT="$REPO_ROOT"

    # Point the soak at the TARGET checkout. WORKTREE IS the clone (the foreign
    # repo is cloned directly, not `git worktree add`'d off the self-repo).
    REPO_ROOT="$FOREIGN_CLONE_TARGET"
    WORKTREE="$FOREIGN_CLONE_TARGET"

    # The gate IS the foreign repo's own command. Red→green gate-visibility uses
    # the existing verify_at_ref against this repo_root (already parameterized).
    GATE_VERIFY_CMD="$TASK_VERIFY_CMD"
    # FAITH_CMD / REVIEW_CMD assume the chimera codebase (chimera faithfulness /
    # chimera review run inside uberagent) — empty for a foreign repo.
    FAITH_CMD=""
    REVIEW_CMD=""

    # `chimera run`'s ADR 0141 branch-drift guard refuses to operate when it
    # detects a non-main branch in what looks like a main worktree. A foreign
    # clone is INTENTIONALLY on a dedicated soak branch and is a throwaway
    # checkout (not the operator's main working copy), so the guard is a false
    # positive here — set the documented operator override for foreign mode only.
    # (Surfaces on a self-clone smoke where the foreign repo is chimera itself;
    # harmless for non-chimera foreign repos.)
    export CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1

    # ADR 0186 B.3: signal foreign-repo context to the agent's prompt builder so
    # it adopts a neutral repo-framed voice/guidance instead of Chimera's
    # self-identity (which would tell the agent it is editing the chimera
    # codebase). Self-mode (TASK_REPO unset) never sets this → byte-identical.
    export CHIMERA_FOREIGN_REPO="$TASK_REPO"
fi

PHASE1_CAP_USD="${PHASE1_CAP_USD:-2.50}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.25}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-7200}"
# Wall-clock reserved for phase 2 (commit + gate). The global MAX_WALL is measured
# from START_EPOCH, so a phase-1 that converges late used to consume the ENTIRE
# wall — phase 2 then started already over-budget and exited in the same second,
# so the agent reached `ruff ✓ pytest ✓` but never committed and the in-loop gate
# never fired (char-0602 finding). Cap phase 1 at MAX_WALL − this reserve so the
# commit phase is always guaranteed time to run.
PHASE2_RESERVE_SECONDS="${PHASE2_RESERVE_SECONDS:-450}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_V40_GATE=1
export CHIMERA_SOAK_RUN_ID="$RUN_ID"
export CHIMERA_ACT_BUDGET_SECONDS="${CHIMERA_ACT_BUDGET_SECONDS:-600}"
# W1 (ADR 0158): the in-loop build-completion gate (check_verify_claim_invalid)
# re-runs THIS command to ground-truth a "prove `chimera verify` is green" task
# — so the agent cannot mark the fix complete while the gate is still red.
export CHIMERA_PHASE1_VERIFY_CMD="$GATE_VERIFY_CMD"
OPERATOR_SUPPRESS_PROPOSALS="${CHIMERA_SUPPRESS_PROPOSALS:-}"
CHIMERA_SOAK_AUTOCOMMIT="${CHIMERA_SOAK_AUTOCOMMIT:-1}"
export CHIMERA_SOAK_AUTOCOMMIT

# LOG lives in the RUNNER's state dir (the chimera self-checkout). In self mode
# RUNNER_ROOT is unset so this resolves to $REPO_ROOT — byte-identical to before.
# In foreign mode RUNNER_ROOT is the self-checkout while REPO_ROOT is the foreign
# clone (not yet created), so the log must NOT live under REPO_ROOT.
LOG="${RUNNER_ROOT:-$REPO_ROOT}/state/real_task_${RUN_ID}.log"

design_note() {
    # ADR 0146 pre-commit scope check: write a design note whose
    # ## READY-FOR-REMEDIATION allowlist == TASK_FILES so the agent's OWN
    # commit passes the scope gate. Without this, the check binds to the
    # newest STALE *-design.md left in the worktree from a prior soak and
    # refuses the commit ("staged paths … outside the allowlist") — the W2
    # finding: the agent's self-commit was blocked and only the harness
    # fallback got through, masking it.
    echo "# Real-task scope: ${TASK_GOAL}"
    echo
    echo "## READY-FOR-REMEDIATION"
    echo
    echo "Allowed scope for this change (the only files the commit may touch):"
    echo
    for f in $TASK_FILES; do echo "- \`$f\`"; done
}

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

**Shell tool usage (important):** the \`shell\` tool runs ONE binary directly —
it is NOT a shell. Do NOT wrap commands in \`bash -c "..."\` / \`sh -c "..."\`
(they are blocked). Call the binary as argv, e.g. argv=["uv","run","ruff",
"check","--fix","<file>"] or argv=["sed","-i","...","<file>"]. Prefer the
file-edit tool for code changes; use \`uv run ruff check --fix\` for lint fixes.

## Phase 1 tasks
- [ ] **Make the change and prove \`chimera verify\` is green.** Edit ONLY the
  files in SCOPE below.
  **FIRST, for any lint/ruff finding, run the auto-fixer — it resolves the
  whole class in one shot and is behaviour-neutral:**
  argv=["uv","run","ruff","check","--fix",<each SCOPE file>]. Do NOT hand-edit
  imports/whitespace ruff can fix itself — hand-edits risk breaking the test
  suite (\`chimera verify\` gates on BOTH ruff AND pytest, so a green ruff with
  a broken pytest still FAILS). After \`--fix\`, run \`${GATE_VERIFY_CMD}\` and
  keep fixing until it exits 0 (\`PASS\`).
- [ ] **Prove the change is FAITHFUL, not just green.** Run
  \`${FAITH_CMD:-uv run chimera faithfulness --target <file> --test <test>}\`.
  A passing suite is not enough: (a) kill every surviving mutant it reports by
  adding a discriminating test (the behaviour is otherwise unpinned), and (b)
  for every behaviour delta vs the base, confirm a failing test DEMANDED it —
  any delta on an input no test covers is a silent regression: revert it or pin
  the intended behaviour with a test. Do NOT make the suite pass by deleting
  untested behaviour.
- [ ] Do NOT commit in phase 1 (engines are off). The runner commits in phase 2.

SCOPE (locked): edit ONLY these files for the fix — ${TASK_FILES}. Operational
journal notes under mind/ are allowed. Anything else is out of scope.
INBOX_EOF
}

if [ "${TASK_DRYRUN:-0}" = "1" ] && [ "$FOREIGN_MODE" = "1" ]; then
    # Foreign-repo dryrun (ADR 0186 B.2): print the RESOLVED foreign config —
    # repo, allowlist decision, clone target, the foreign gate — and exit
    # WITHOUT cloning or running any soak. The allowlist already fail-closed
    # above for a non-allowlisted repo, so reaching here means ALLOWED.
    echo "=== real_task_soak.sh config (dryrun · FOREIGN repo · ADR 0186 B.2) ==="
    echo "  goal        = $TASK_GOAL"
    echo "  files       = $TASK_FILES"
    echo "  test        = ${TASK_TEST:-<full suite>}"
    echo "  base        = $TASK_BASE"
    echo "  run id      = $RUN_ID"
    echo "  repo        = $TASK_REPO"
    echo "  allowlist   = $CHIMERA_REPO_ALLOWLIST"
    echo "  allow       = $FOREIGN_ALLOW_DECISION"
    echo "  clone target= $FOREIGN_CLONE_TARGET"
    echo "  gate cmd    = $GATE_VERIFY_CMD   (= TASK_VERIFY_CMD, the foreign repo's own gate)"
    echo "  faith cmd   = <none: foreign repo (chimera faithfulness assumes the self-repo)>"
    echo "  review cmd  = <none: foreign repo (chimera review assumes the self-repo)>"
    echo "  autocommit  = $CHIMERA_SOAK_AUTOCOMMIT"
    echo "  worktree    = $WORKTREE"
    echo "  handoff     = draft-PR-only / manual-handoff — NO cross-repo push, NO auto-merge"
    echo "  scope note  = mind/research/realtask-${RUN_ID}-design.md"
    echo "--- scope design note (ADR 0146 allowlist) ---"
    design_note
    echo "--- phase-1 INBOX ---"
    phase1_inbox
    echo "--- (dryrun) NOT cloning, NOT running a soak ---"
    exit 0
fi

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    echo "=== real_task_soak.sh config (dryrun) ==="
    echo "  goal      = $TASK_GOAL"
    echo "  files     = $TASK_FILES"
    echo "  test      = ${TASK_TEST:-<full suite>}"
    echo "  base      = $TASK_BASE"
    echo "  run id    = $RUN_ID"
    echo "  gate cmd  = $GATE_VERIFY_CMD"
    echo "  faith cmd = ${FAITH_CMD:-<none: TASK_TEST unset>}"
    echo "  review cmd= $REVIEW_CMD"
    echo "  autocommit= $CHIMERA_SOAK_AUTOCOMMIT"
    echo "  worktree  = $WORKTREE"
    echo "  scope note= mind/research/realtask-${RUN_ID}-design.md"
    echo "--- scope design note (ADR 0146 allowlist) ---"
    design_note
    echo "--- phase-1 INBOX ---"
    phase1_inbox
    exit 0
fi

# In self mode RUNNER_ROOT is unset → resolves to $REPO_ROOT (byte-identical).
# In foreign mode the runner's state dir (for the log) lives under RUNNER_ROOT,
# not the foreign clone.
mkdir -p "${RUNNER_ROOT:-$REPO_ROOT}/state"
START_EPOCH="$(date +%s)"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "real_task_soak.sh — $TASK_GOAL"
log "  run id   = $RUN_ID   base = $TASK_BASE"
log "  gate cmd = $GATE_VERIFY_CMD"
log "─────────────────────────────────────────────────────────────"

if [ -e "$WORKTREE" ]; then log "FATAL: worktree exists: $WORKTREE"; exit 2; fi
if [ "$FOREIGN_MODE" = "1" ]; then
    # ── Foreign-repo checkout (ADR 0186 B.2) ──────────────────────────────
    # Clone the ALLOWLISTED target into the managed workspace and create the
    # soak branch there. The foreign repo IS the WORKTREE (a standalone clone,
    # not a `git worktree add` off the self-repo). Prefer `gh repo clone`
    # (honours auth/SSO); fall back to an HTTPS `git clone`.
    log "── foreign mode (ADR 0186 B.2): repo=$TASK_REPO allow=$FOREIGN_ALLOW_DECISION ──"
    log "  cloning $TASK_REPO → $WORKTREE"
    if command -v gh >/dev/null 2>&1 && gh repo clone "$TASK_REPO" "$WORKTREE" -- --branch "$TASK_BASE" 2>&1 | tee -a "$LOG"; then
        :
    else
        log "  gh clone unavailable/failed; falling back to https git clone"
        git clone --branch "$TASK_BASE" "https://github.com/${TASK_REPO}.git" "$WORKTREE" 2>&1 | tee -a "$LOG" \
            || { log "FATAL: clone of $TASK_REPO failed"; exit 2; }
    fi
    cd "$WORKTREE" || { log "FATAL: cd foreign clone"; exit 2; }
    git checkout -b "$BRANCH" 2>&1 | tee -a "$LOG" || { log "FATAL: create soak branch"; exit 2; }
    # Disable push on the foreign remote — draft-PR-only / manual-handoff: the
    # runner NEVER pushes to a foreign origin in B.2 (no cross-repo push).
    git config remote.origin.pushurl "no-push://foreign-disabled-${RUN_ID}" 2>&1 | tee -a "$LOG" || true
else
    git worktree add -b "$BRANCH" "$WORKTREE" "$TASK_BASE" 2>&1 | tee -a "$LOG"
    cd "$WORKTREE" || { log "FATAL: cd worktree"; exit 2; }
    git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
    git config --worktree remote.origin.pushurl "no-push://disabled-${RUN_ID}" 2>&1 | tee -a "$LOG" || true
fi

WORKTREE_STATE="$WORKTREE/state"; WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"
# Trust + calibration records are the RUNNER's (chimera's) state; in self mode
# RUNNER_ROOT is unset → $REPO_ROOT (byte-identical). In foreign mode the source
# is the chimera self-checkout, not the foreign clone.
[ -f "${RUNNER_ROOT:-$REPO_ROOT}/state/trust_state.json" ] && cp "${RUNNER_ROOT:-$REPO_ROOT}/state/trust_state.json" "$WORKTREE_STATE/"
# ADR 0162: carry the calibration record into the worktree so the in-loop critic
# gate's calibration-gated activation can verify it (enforce-ON soaks need it; a
# no-op when absent / enforcement off).
[ -f "${RUNNER_ROOT:-$REPO_ROOT}/state/critic-calibration-latest.json" ] && \
    cp "${RUNNER_ROOT:-$REPO_ROOT}/state/critic-calibration-latest.json" "$WORKTREE_STATE/"
export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"
mkdir -p "$WORKTREE/mind/research"

# W2 fix: write the scope design note (ADR 0146 allowlist = TASK_FILES) so the
# agent's OWN commit passes the pre-commit scope check, instead of being refused
# against a stale design note left in the worktree by a prior soak. Written here
# (post-worktree, pre-phase-1) so it is the newest *-design.md by mtime — the one
# find_active_design_note() binds to.
DESIGN_NOTE="$WORKTREE/mind/research/realtask-${RUN_ID}-design.md"
design_note > "$DESIGN_NOTE"
log "scope design note written: mind/research/realtask-${RUN_ID}-design.md (allowlist: $TASK_FILES)"

# Source soak_lib from the RUNNER checkout (REPO_ROOT, captured pre-cd), NOT a
# relative path — after `cd "$WORKTREE"` a relative source loads the worktree's
# (possibly stale) copy, which silently ran an old soak_lib all session. In
# foreign mode REPO_ROOT is the foreign clone (no soak_lib), so source from
# RUNNER_ROOT; in self mode RUNNER_ROOT is unset → $REPO_ROOT (byte-identical).
source "${RUNNER_ROOT:-$REPO_ROOT}/scripts/soak_lib.sh"
log "$(soak_lib_version)"

phase_loop() {
    local phase_name="$1" cap_usd="$2" phase_start_iso="$3" engines_enabled="$4"
    # 5th arg: effective wall (seconds from START_EPOCH) for THIS phase. Phase 1
    # gets MAX_WALL − PHASE2_RESERVE so it can't starve the commit phase; phase 2
    # gets the full MAX_WALL. Defaults to the global wall for any other caller.
    local phase_wall="${5:-$MAX_WALL_SECONDS}"
    local cap_minus_buffer; cap_minus_buffer="$(awk -v c="$cap_usd" -v b="$SAFETY_BUFFER_USD" 'BEGIN { print c - b }')"
    export CHIMERA_ENGINES_ENABLED="$engines_enabled"
    if [ "$engines_enabled" = "1" ]; then
        export CHIMERA_SUPPRESS_PROPOSALS="${OPERATOR_SUPPRESS_PROPOSALS:-1}"
    else
        unset CHIMERA_SUPPRESS_PROPOSALS
    fi
    local iter=0 exit_reason=""
    soak_reset_forward_progress
    log "── $phase_name start: cap=\$$cap_usd engines=$engines_enabled wall=${phase_wall}s ──"
    while : ; do
        iter=$((iter+1))
        [ "$iter" -gt "$MAX_ITERATIONS_PER_PHASE" ] && { exit_reason="max_iterations"; break; }
        local now; now="$(date +%s)"
        [ $((now - START_EPOCH)) -ge "$phase_wall" ] && { exit_reason="max_wall_seconds"; break; }
        local spend; spend="$(total_spend_in_db "$WORKTREE_DB" "$phase_start_iso")"
        fp_ge "$spend" "$cap_minus_buffer" && { exit_reason="phase_budget_reached spend=\$$spend"; break; }
        local cycle_pre; cycle_pre="$(last_cycle_in_db "$WORKTREE_DB")"
        if ! soak_check_forward_progress "$cycle_pre" "$spend"; then exit_reason="no_forward_progress cycle=$cycle_pre"; break; fi
        log "$phase_name iter $iter  cycle=$cycle_pre  spend=\$$spend  cap=\$$cap_usd"
        soak_run_chimera_with_watchdog "$WORKTREE" "$LOG" || log "  watchdog fired ($phase_name iter $iter)"
        if [ "$engines_enabled" = "1" ] && [ "$CHIMERA_SOAK_AUTOCOMMIT" = "1" ]; then
            local msg="[agent] ${TASK_GOAL} — harness-committed (ADR 0148): agent authored+verified; runner executed the commit."
            if [ "$FOREIGN_MODE" = "1" ]; then
                # Foreign repo: there is no chimera package to import for
                # soak_autocommit, so run the foreign repo's OWN gate
                # ($GATE_VERIFY_CMD = TASK_VERIFY_CMD) and, if green, commit the
                # allowlisted files in the foreign checkout. The chimera scope
                # (ADR 0146) / critic (ADR 0160) gates do not apply to a foreign
                # repo (FAITH_CMD/REVIEW_CMD are empty in foreign mode). DRAFT-only:
                # NO push, NO merge — the branch stays in the foreign checkout.
                local st
                if soak_gate_run "$WORKTREE" "$GATE_VERIFY_CMD" >>"$LOG" 2>&1; then
                    # shellcheck disable=SC2086  # intentional word-split of the allowlist
                    # `git reset` first so ONLY the allowlist is staged — a foreign
                    # PR must never carry files outside TASK_FILES even if something
                    # was pre-staged (B.4e review; the PR's allowlist-scoping is the
                    # load-bearing safety property behind the standing-trust gate).
                    st="$(cd "$WORKTREE" && git reset -q HEAD -- . 2>/dev/null; \
                        git add -- $TASK_FILES 2>/dev/null; \
                        if git diff --cached --quiet; then echo no_changes_in_scope; \
                        elif git commit -q -m "$msg"; then echo committed; \
                        else echo commit_failed; fi)"
                else
                    st="gate_red"
                fi
                log "  harness-autocommit (foreign): ${st:-error}"
                # B.4g — enforce the scope invariant on the WORKING TREE. The agent
                # may leave OUT-OF-SCOPE residue uncommitted (most often a tree-wide
                # `ruff --fix` that strips unused imports across the whole foreign
                # repo, or a scratch file); chimera's in-loop scope_check is staged-
                # index-only and is blind to it. The allowlist is already committed,
                # so revert everything else to HEAD (keeping operational dirs) — a
                # foreign PR must carry ONLY $TASK_FILES. LOUDLY logged: an over-
                # running agent stays visible, never silently masked.
                _residue="$(cd "${RUNNER_ROOT:-$REPO_ROOT}" && uv run python -c "
from chimera.core.submit_pr import revert_out_of_scope_residue
for p in revert_out_of_scope_residue('$WORKTREE', keep_prefixes=('mind/','state/','.venv/')):
    print(p)" 2>>"$LOG")"
                if [ -n "$_residue" ]; then
                    log "  ⚠ B.4g reverted OUT-OF-SCOPE residue (foreign PR carries only \$TASK_FILES):"
                    printf '%s\n' "$_residue" | while IFS= read -r _l; do log "      $_l"; done
                fi
            else
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
# ADR 0186 B.3b: append foreign-repo context (the target's README/docs + the
# current failing gate output) to the INBOX so the agent reasons about the
# TARGET repo, not chimera. Self mode (FOREIGN_MODE=0) leaves the INBOX exactly
# as phase1_inbox produced it — byte-identical.
if [ "$FOREIGN_MODE" = "1" ]; then
    log "── B.3b: capturing foreign context (README + baseline gate output) ──"
    # Capture the CURRENT (red) gate output. The foreign verify_cmd is already
    # executed unsandboxed by the B.2 gate, so this is the same surface (B.4
    # sandboxes ALL foreign-code runs). Bounded by a portable timeout when one is
    # available so a hung suite can't stall setup. cwd is the clone (WORKTREE).
    # Secrets are stripped from the capture too (ADR 0186 B.4 M1) — env -u via
    # soak_secret_unset_args, before the optional timeout wrapper. cwd is the clone.
    _to_bin="$(command -v timeout || command -v gtimeout || true)"
    # shellcheck disable=SC2046  # intentional word-split of the -u flag list
    if [ -n "$_to_bin" ]; then
        _gate_out="$(env $(soak_secret_unset_args) "$_to_bin" "${FOREIGN_GATE_TIMEOUT:-300}" sh -c "$GATE_VERIFY_CMD" 2>&1 | tail -200 || true)"
    else
        _gate_out="$(env $(soak_secret_unset_args) sh -c "$GATE_VERIFY_CMD" 2>&1 | tail -200 || true)"
    fi
    # Build the context block with the chimera helper, run from RUNNER_ROOT (the
    # chimera package is NOT in a non-chimera foreign clone). The helper reads the
    # README from the absolute worktree path, so cwd there is irrelevant.
    {
        printf '\n\n---\n\n'
        ( cd "${RUNNER_ROOT:-$REPO_ROOT}" \
          && CHIMERA_FOREIGN_GATE_OUTPUT="$_gate_out" \
             FOREIGN_WT="$WORKTREE" FOREIGN_REPO="$TASK_REPO" FOREIGN_GATE_CMD="$GATE_VERIFY_CMD" \
             uv run python -c '
import os
from pathlib import Path
from chimera.core.foreign_context import foreign_context_block
print(foreign_context_block(
    Path(os.environ["FOREIGN_WT"]), os.environ["FOREIGN_REPO"],
    os.environ["FOREIGN_GATE_CMD"], os.environ.get("CHIMERA_FOREIGN_GATE_OUTPUT", "")))
' )
    } >> "$WORKTREE/mind/INBOX.md"
    log "── B.3b: foreign context appended to INBOX ──"
fi
log "phase-1 INBOX seeded ($TASK_GOAL)"
P1_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
# Phase 1 stops PHASE2_RESERVE_SECONDS before the global wall, guaranteeing the
# commit phase a budget even when phase 1 converges late.
#
# CRITICAL: the per-phase wall is only checked BETWEEN iterations, so a phase-1
# ACT iteration that starts just under the cap runs a full CHIMERA_ACT_BUDGET and
# overruns the soft cap by up to one ACT budget. If the reserve ≤ one ACT budget,
# that overrun blows past the GLOBAL wall and phase 2 starts already over-budget
# → zero time → the agent reaches green but never commits (e2e single-launch
# finding 2026-06-03; #246 reserve=450 < ACT budget 600 was a partial fix). Floor
# the reserve at one ACT budget + cooldown + margin so phase 1's last iteration
# still ends before the global wall and phase 2's first iteration clears its check
# (then runs a full ACT iteration to commit, governed by the ACT/watchdog budget).
_min_reserve=$(( ${CHIMERA_ACT_BUDGET_SECONDS:-600} + COOLDOWN_SECONDS + 60 ))
[ "$PHASE2_RESERVE_SECONDS" -lt "$_min_reserve" ] && PHASE2_RESERVE_SECONDS="$_min_reserve"
PHASE1_WALL=$(( MAX_WALL_SECONDS - PHASE2_RESERVE_SECONDS ))
[ "$PHASE1_WALL" -lt 60 ] && PHASE1_WALL=60
log "  phase walls: phase1=${PHASE1_WALL}s  phase2-reserve=${PHASE2_RESERVE_SECONDS}s  (act_budget=${CHIMERA_ACT_BUDGET_SECONDS:-600}s, global=${MAX_WALL_SECONDS}s)"
phase_loop "phase1" "$PHASE1_CAP_USD" "$P1_ISO" "0" "$PHASE1_WALL"

# Phase 2: commit (engines on).
P2_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — real-task soak phase 2 (commit-only, engines on)

Phase 1 made the change and \`chimera verify\` passes. Your ONE job now: COMMIT it.

## Phase 2 — call git_commit FIRST (this is your very first action)
- [ ] Call the **\`git_commit\` tool** immediately: \`git_commit\` with
  message="${TASK_GOAL}" and paths=[${TASK_FILES}]. This SINGLE tool call stages
  AND commits AND returns the new HEAD — it IS the entire commit. The \`[agent]\`
  prefix is added for you.
  - Do NOT run \`git add\` yourself, and do NOT stop after staging: raw staging
    WITHOUT a following commit leaves the change uncommitted and the run FAILS
    (this is the #1 way this phase fails — staged but never committed).
  - You do NOT need to run \`chimera review\` or re-run \`chimera verify\` first.
    The in-loop critic gate adjudicates faithfulness AUTOMATICALLY as part of the
    \`git_commit\` call — committing IS how the change gets reviewed.
- [ ] ONLY if \`git_commit\` returns that the gate REJECTED: read the concern, fix
  it in SCOPE (${TASK_FILES}), then call \`git_commit\` again until HEAD advances.

Manual-handoff: after the commit the runner stops with the branch in the
worktree — NO auto-push/PR/merge.
INBOX_EOF
log "phase-2 INBOX seeded"
# Diagnostic (finding #2): record whether the in-loop critic gate will actually
# engage on the agent's commit — its two preconditions, visible in the log.
log "  critic-gate state: CHIMERA_CRITIC_ENFORCE=${CHIMERA_CRITIC_ENFORCE:-<unset>}  calibration_record=$([ -f "$WORKTREE_STATE/critic-calibration-latest.json" ] && echo present || echo MISSING)"
phase_loop "phase2" "$PHASE2_CAP_USD" "$P2_ISO" "1" "$MAX_WALL_SECONDS"

log "── branch commits (expect 1 [agent] commit) ──"
( cd "$WORKTREE" && git log --oneline "$TASK_BASE"..HEAD ) 2>&1 | tee -a "$LOG"
log "── gate (post-fix) ──"
soak_gate_run "$WORKTREE" "$GATE_VERIFY_CMD" 2>&1 | tee -a "$LOG"
GATE_RC=${PIPESTATUS[0]}
log "Review: cd $WORKTREE && git log --oneline $TASK_BASE..HEAD"

# Evidence (ADR 0182 Phase 3): one stable machine-readable outcome line the
# CRAWL runner records into the outcome ledger. Fields the runner needs to
# accrue the RUN-graduation metrics (gate-pass rate, cost, disposition).
[ "${GATE_RC:-1}" -eq 0 ] && SOAK_GATE=pass || SOAK_GATE=fail
SOAK_COMMITTED="$(cd "$WORKTREE" && git log --format='%s' "$TASK_BASE"..HEAD 2>/dev/null | grep -c '\[agent\]' || echo 0)"
# Accurate total from the worktree's api_calls (recomputed from tokens × price).
# NOT the log's per-phase 'spend=' lines — phase 2 resets that counter, so a
# tail-of-log read reported $0.00 (2026-06-14 finding).
SOAK_COST="$(cd "$WORKTREE" && uv run chimera cost --json 2>/dev/null | uv run python -c 'import sys,json; print(json.load(sys.stdin).get("total_usd", 0))' 2>/dev/null || echo 0)"
log "[soak-outcome] run_id=${RUN_ID} branch=${BRANCH} gate=${SOAK_GATE} committed=${SOAK_COMMITTED:-0} cost_usd=${SOAK_COST:-0} base=${TASK_BASE}"

# ADR 0186 B.2 — FOREIGN repo: draft-PR-only / manual-handoff. The runner stops
# with the soak branch in the foreign clone for review; it does NOT auto-merge
# and does NOT push to the foreign origin (its pushurl is disabled above).
#
# ADR 0186 B.4: foreign draft-PR targeting has LANDED — maybe_foreign_pr (via the
# `chimera foreign-pr submit` verb below) opens a trust-gated DRAFT PR on the
# target (≥ T4, draft-only, never merges, allowlist + verify_cmd-review + first-5
# approval). It is OFF by default (CHIMERA_FOREIGN_PR unset) → foreign runs stay
# manual-handoff exactly as before until the operator opts in AND approves.
if [ "$FOREIGN_MODE" = "1" ]; then
    # ADR 0186 B.4d: when opted in (CHIMERA_FOREIGN_PR set), attempt a trust-gated
    # DRAFT PR on the target. EVERY gate lives in maybe_foreign_pr (opt-in,
    # allowlist, trust>=T4, gate-approved-commit, verify_cmd-review, first-5
    # approval) — this is a no-op when not opted in/approved. Run from RUNNER_ROOT
    # (chimera is installed there, not in the foreign clone) and point the
    # GOVERNANCE ledger at the operator's PERSISTENT state, NOT the throwaway
    # clone's CHIMERA_STATE_DIR (which is deleted with the workspace).
    if [ -n "${CHIMERA_FOREIGN_PR:-}" ]; then
        # CHIMERA_FOREIGN_PR_DRY_RUN=1 exercises the WHOLE path (gates → submit)
        # without pushing or opening a PR — the safe rehearsal before a first live
        # foreign run on a new repo (ADR 0186 B.4d).
        _fpr_dry=""
        [ -n "${CHIMERA_FOREIGN_PR_DRY_RUN:-}" ] && _fpr_dry="--dry-run"
        # shellcheck disable=SC2086  # _fpr_dry is a single optional flag
        ( cd "${RUNNER_ROOT:-$REPO_ROOT}" && uv run chimera foreign-pr submit \
            --repo "$TASK_REPO" --worktree "$WORKTREE" --base "$TASK_BASE" \
            --verify-cmd "$TASK_VERIFY_CMD" \
            --run-id "$RUN_ID" --state-dir "${RUNNER_ROOT:-$REPO_ROOT}/state" $_fpr_dry ) 2>&1 | tee -a "$LOG" || true
    fi
    log "── foreign mode: branch '$BRANCH' left in $WORKTREE for review ──"
    log "Review: cd $WORKTREE && git log --oneline $TASK_BASE..HEAD"
    exit 0
fi

# ADR 0163: trust-gated autonomous self-PR. Centralized HERE (the lowest common
# denominator — both real-task and self-determined/charter runs funnel through
# this runner) so the originate→build→gate→commit→self-PR chain completes in ONE
# launch. OFF by default: fires only under CHIMERA_SELF_PR=1, and maybe_self_pr
# itself re-checks every gate (trust ≥ T4, a gate-approved commit, full
# submit_pr.validate()) and opens a DRAFT PR that never merges. Inert when unset
# → the manual-handoff status quo. The PR targets SELF_PR_BASE (default main).
# (Self-repo only — the foreign-mode early-exit above prevents reaching this.)
if [ "${CHIMERA_SELF_PR:-0}" = "1" ]; then
    has_agent="$(cd "$WORKTREE" && git log --format='%s' "$TASK_BASE"..HEAD 2>/dev/null | grep -c '\[agent\]')"
    if [ "${has_agent:-0}" -ge 1 ]; then
        log "── self-PR (ADR 0163): CHIMERA_SELF_PR=1, attempting trust-gated draft PR ──"
        selfpr="$(cd "$REPO_ROOT" && SELF_PR_BASE="${SELF_PR_BASE:-main}" uv run python -c "
import json, os
from chimera.core.self_pr import maybe_self_pr
r = maybe_self_pr(worktree='$WORKTREE', repo_root='$REPO_ROOT',
                  base=os.environ.get('SELF_PR_BASE', 'main'))
print(json.dumps(r.to_dict()))" 2>&1 | tail -1)"
        log "  self-PR result: $selfpr"
    fi
fi
exit 0
