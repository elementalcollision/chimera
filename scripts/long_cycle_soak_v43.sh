#!/usr/bin/env bash
# scripts/long_cycle_soak_v43.sh — R3 build-capability, ladder rung 4
# (parallel fan-out: THREE independent single-file builds in ONE soak, N=3).
#
# Charter: mind/research/v43-parallel-builds-design.md. v40′/v41/v42 cleared
# rungs 1–3 (tiny → moderate → multi-file). v43 escalates the ONLY variable
# not yet probed: fan-out breadth. Each of the three targets is a single,
# self-contained module of v40′/v41-tier difficulty (no import boundary —
# that was v42's lesson, already learned). The new question is task management
# and isolation at N=3: can the loop select / build / verify / commit /
# honestly-report on three independent charters in one run without dropping a
# task, conflating targets, mis-binding a scope check, or letting one target's
# failure contaminate another.
#
# Targets (THREE new standalone modules, mutually independent):
#   chimera/strcase.py   (to_snake, to_camel)         — tests/test_strcase.py
#   chimera/numfmt.py    (human_bytes, clamp)         — tests/test_numfmt.py
#   chimera/seqstats.py  (running_max, dedupe_stable) — tests/test_seqstats.py
# All three tests are on main, gated by CHIMERA_V40_GATE, currently failing.
# None imports the others or any existing source; tested DIRECTLY (no CLI), so
# a regression in one cannot brick `chimera run` or the other two builds.
#
# The AND across all three (target, test) pairs is enforced by the COMBINED
# gate command: the phase-1 / phase-2 soft-sentinels run all three test files
# at once, so phase exit requires every one of the 17 assertions green — a
# target left unbuilt keeps its test red and the phase continues. Phase 1 also
# requires (strict mode) that ALL THREE postmortems carry the READY marker, so
# it cannot exit "landed" with any deliverable unwritten.
#
# Three commits (one [agent] commit per module, each scoped to its own file);
# three postmortems (one per target, each independently honesty-checked at
# write time by Rules A–E — the post-v42 numeric-honesty hardening landed
# precisely because three postmortems are too many to hand-audit).
#
# Cost: hard cap $6.00 total ($2.00/build). Runs on the fully hardened
# substrate (H1/H2/H3 + B1/B2 + postmortem numeric honesty).
#
# Inherits post-cascade hardening by cloning v42's scaffold: forward-progress
# + task-completion watchdogs, ACT-budget enforcement, pre-commit scope check
# (ADR 0146), ADR 0141 worktree detector, SQLite thread-affinity fix, phase-1
# soft-sentinel (here in strict all-markers mode).
#
# Manual-handoff (PR #111): NO auto-push, NO auto-PR, NO auto-merge. The
# runner stops with the branch in the worktree for operator review.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v43.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v43-trio-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v43-$STAMP}"

# Cost gate (design note gate 4): $6.00 total hard cap ($2/build). Split
# across the two phases with a rolling-hour ceiling as the true envelope.
PHASE1_CAP_USD="${PHASE1_CAP_USD:-4.50}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.25}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-300}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-10800}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

SOAK_TRUST_DROP_THRESHOLD="${SOAK_TRUST_DROP_THRESHOLD:-2}"
SOAK_AUTO_PROMOTE_ON_DEGRADE="${SOAK_AUTO_PROMOTE_ON_DEGRADE:-1}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-6.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1
export CHIMERA_ENGINE_SESSION_MODE=1

# Gate env + soak ledgers.
export CHIMERA_V40_GATE=1
export CHIMERA_SOAK_RUN_ID="v43-trio-$STAMP"

# Test-driven build tasks bundle read+implement+run-test+iterate into one ACT
# phase; give each room to actually loop (v40-#2 lesson).
export CHIMERA_ACT_BUDGET_SECONDS="${CHIMERA_ACT_BUDGET_SECONDS:-600}"

# The COMBINED pytest gate over all three targets, used by BOTH soft-sentinels
# and the post-soak primary gate. Exits 0 only when every target's test passes
# — this is the AND across all three (target, test) pairs. No env prefix (the
# argv-only shell tool rejects it; CHIMERA_V40_GATE is exported above and
# inherited). `uv run --extra dev` uses the worktree venv with pytest.
GATE_TEST_CMD="uv run --extra dev pytest -q tests/test_strcase.py tests/test_numfmt.py tests/test_seqstats.py"

READY_MARKER="## READY-FOR-REMEDIATION"
LOG="$REPO_ROOT/state/long_cycle_v43_${STAMP}.log"
mkdir -p "$REPO_ROOT/state"
: > "$LOG"

START_EPOCH="$(date +%s)"

log() { local ts; ts="$(date '+%H:%M:%S')"; printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG"; }

total_spend_in_db() {
    sqlite3 "$1" \
        "SELECT COALESCE(ROUND(SUM(cost_usd), 4), 0.0) FROM api_calls WHERE created_at >= '$2';" \
        2>/dev/null || echo "0.0"
}

last_cycle_in_db() {
    sqlite3 "$1" "SELECT COALESCE(MAX(cycle), 0) FROM api_calls;" 2>/dev/null || echo "0"
}

fp_ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit (a+0 >= b+0) ? 0 : 1 }'; }

current_trust_tier() {
    local f="$1/trust_state.json"
    [ -f "$f" ] || { echo 0; return; }
    python3 -c "import json,sys
try:
    print(int(json.load(open('$f')).get('current_tier', 0)))
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

soak_check_trust_degradation() {
    local baseline="$1"
    local phase_name="$2"
    local extra_args=()
    if [ "$SOAK_AUTO_PROMOTE_ON_DEGRADE" = "1" ]; then
        extra_args+=( --auto-promote )
    fi
    ( cd "$WORKTREE" && uv run chimera trust degrade-check \
        --baseline "$baseline" \
        --threshold-drop "$SOAK_TRUST_DROP_THRESHOLD" \
        --chronicle-path "$WORKTREE/mind/SESSION_LOG.md" \
        "${extra_args[@]}" ) >> "$LOG" 2>&1
    local rc=$?
    if [ "$rc" = "10" ]; then
        log "  ⚠️  $phase_name trust degraded vs baseline=T$baseline (see SESSION_LOG.md)"
    fi
    return 0
}

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v43.sh — R3 build-capability, PARALLEL fan-out (N=3)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  run id         = $CHIMERA_SOAK_RUN_ID"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — build all 3 + test, no commit)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, 3 commits)"
log "  hard cap       = \$$CHIMERA_ROLLING_HOUR_CAP_USD (rolling-hour envelope)"
log "  gate test cmd  = $GATE_TEST_CMD"
log "─────────────────────────────────────────────────────────────"

# ── doctor pre-flight ──────────────────────────────────────────
if ! ( cd "$REPO_ROOT" && uv run chimera doctor >/dev/null 2>&1 ); then
    log "WARN: chimera doctor reported issues (continuing; soak runs in worktree)"
fi

# ── worktree provisioning ──────────────────────────────────────
if [ -e "$WORKTREE" ]; then
    log "FATAL: worktree path already exists: $WORKTREE"
    exit 2
fi
git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"
cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v43-$STAMP" 2>&1 | tee -a "$LOG" || true

WORKTREE_STATE="$WORKTREE/state"
WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"

if [ -f "$REPO_ROOT/state/trust_state.json" ]; then
    cp "$REPO_ROOT/state/trust_state.json" "$WORKTREE_STATE/trust_state.json"
    log "seeded trust state from main"
fi
if [ -f "$REPO_ROOT/state/tiers.json" ]; then
    cp "$REPO_ROOT/state/tiers.json" "$WORKTREE_STATE/tiers.json"
fi

export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"

DELIVERABLE_STRCASE="mind/research/v43-strcase-postmortem.md"
DELIVERABLE_NUMFMT="mind/research/v43-numfmt-postmortem.md"
DELIVERABLE_SEQSTATS="mind/research/v43-seqstats-postmortem.md"
ALL_POSTMORTEMS="$DELIVERABLE_STRCASE $DELIVERABLE_NUMFMT $DELIVERABLE_SEQSTATS"
ALL_MODULES="chimera/strcase.py chimera/numfmt.py chimera/seqstats.py"
mkdir -p "$WORKTREE/mind/research"

# ── phase-1 INBOX — CREATE all three modules, iterate to green, 3 postmortems ─
cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — Soak v43 phase 1 (PARALLEL BUILD ×3; engines off, no commits yet)

**Chip**: create THREE independent new modules so their pre-written tests
pass. You are writing code, not classifying. The three are mutually
independent — no module imports another or any existing source.
**Atomic op class**: code + postmortem, ×3. **Code goes in THREE NEW files:
\`chimera/strcase.py\`, \`chimera/numfmt.py\`, \`chimera/seqstats.py\`. Do
NOT touch \`chimera/cli.py\` or any other existing source.**

## The contracts live in the tests (read each; do NOT edit them)

Three pre-written tests are on main and define the exact behavior. READ each
to discover its contract. You MUST NOT modify any of them — the pre-commit
scope check refuses any commit that touches a test, and doing so falsifies
the soak.

Run the COMBINED gated test to see the current red state and to check
progress. Run it EXACTLY as written, via the shell tool, with argv
["uv","run","--extra","dev","pytest","-q","tests/test_strcase.py","tests/test_numfmt.py","tests/test_seqstats.py"]:

    $GATE_TEST_CMD

Notes:
  - Do NOT prefix the command with \`CHIMERA_V40_GATE=1\`. That env var is
    already set and inherited; the shell tool is argv-only and will REJECT an
    env-assignment prefix as a non-allow-listed program.
  - Use \`uv run --extra dev\` (NOT bare \`python3 -m pytest\`).
  - Pre-implementation you will see 17 failed. All three modules correct →
    17 passed (NOT "17 skipped" — skipped means the gate env is missing, which
    it is not here). You can also run a single test file to focus on one
    target, but the soak is not done until the COMBINED command shows
    \`17 passed\`.

## Phase 1 tasks — THREE independent builds, each a cohesive task

Each build is ONE task: read its test, create its module, run the test, iterate
to green. A build is NOT done until you have RUN its test and SEEN it pass.
The three are independent — finishing one does not touch the others.

- [ ] **Build \`chimera/strcase.py\` and prove green.** Read
  \`tests/test_strcase.py\` for the EXACT contract (\`to_snake\`, \`to_camel\`),
  CREATE the module, run the gated command, iterate until its assertions pass.
- [ ] **Build \`chimera/numfmt.py\` and prove green.** Read
  \`tests/test_numfmt.py\` (\`human_bytes\`, \`clamp\`), CREATE the module,
  run, iterate to green.
- [ ] **Build \`chimera/seqstats.py\` and prove green.** Read
  \`tests/test_seqstats.py\` (\`running_max\`, \`dedupe_stable\`), CREATE the
  module, run, iterate to green.
- [ ] **Confirm all three together**: run \`$GATE_TEST_CMD\` and see
  \`17 passed\`. Do not mark the builds complete on the strength of having
  written code — only on a green combined run you actually executed.
- [ ] **Write THREE postmortems**, one per target (ONLY after 17 passed),
  using \`mind/postmortems/TEMPLATE-soak-postmortem.md\`:
  \`$DELIVERABLE_STRCASE\`, \`$DELIVERABLE_NUMFMT\`, \`$DELIVERABLE_SEQSTATS\`.
  Each fills the iteration-vs-spend table from the ledgers under
  \`mind/soak/$CHIMERA_SOAK_RUN_ID/\`, does the verdict-honesty cross-check,
  and ends with the \`## READY-FOR-REMEDIATION\` fenced block. **Read the
  numbers — do NOT estimate.** \`act_cycles\` (= summarize_run().act_cycles)
  and \`spend_usd\` (= \`chimera cost\`) are CHECKED at write time; a drifted
  number trips the honesty gate exactly like a dishonest \`tests_passing\`.
  **These two are RUN-CUMULATIVE (whole-soak totals), NOT per-build:** all
  THREE postmortems report the SAME act_cycles and spend_usd (the run
  totals from summarize_run / chimera cost). Do NOT divide them by three or
  attribute a per-build slice — the gate compares against the cumulative
  ledger and rejects a per-build under-count.

## The contracts are EXACT — match them, don't summarize

Each test asserts EXACT values. Read each test's expected outputs and match
them precisely; do not approximate. Keep ALL imports at module top-level in
every file (a function-local import shadows the module name and raises
UnboundLocalError; a pre-commit gate refuses it).

SCOPE (locked): create/edit ONLY the three \`chimera/{strcase,numfmt,seqstats}.py\`
files for code; write ONLY the three postmortems under mind/research/. Do NOT
edit any test, do NOT touch \`chimera/cli.py\` or any other existing source,
any ADR, or pyproject.toml. No CLI wiring — these are three standalone modules.

OVERSHOOT TRAPS the panel should reject:
  - Editing any of the three test files (read-only; refused at commit)
  - Touching \`chimera/cli.py\` or any code file other than the three targets
  - Claiming a build passes without running the gated command (the test-run
    ledger records ground truth)
  - Output not matching a test's exact expected values
  - A function-local import that shadows a module name
  - Emitting a READY marker with that target still red
  - Estimating act_cycles / spend_usd instead of reading them
INBOX_EOF

log "phase-1 INBOX seeded (v43 R3 parallel build: 3 independent modules)"

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"

source "$(dirname "$0")/soak_lib.sh"
log "$(soak_lib_version)"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""
SOFT_SENTINEL_REQUIRE_ALL_MARKERS=""

phase_loop() {
    local phase_name="$1"
    local cap_usd="$2"
    local phase_start_iso="$3"
    local sentinel_path="${4:-}"
    local engines_enabled="${5:-1}"

    local cap_minus_buffer
    cap_minus_buffer="$(awk -v c="$cap_usd" -v b="$SAFETY_BUFFER_USD" 'BEGIN { print c - b }')"

    export CHIMERA_ENGINES_ENABLED="$engines_enabled"

    local iter=0
    local exit_reason=""
    local trust_baseline
    trust_baseline="$(current_trust_tier "$WORKTREE_STATE")"
    soak_reset_forward_progress

    log "── $phase_name start: cap=\$$cap_usd engines=$engines_enabled baseline=$phase_start_iso trust=T$trust_baseline ──"

    while : ; do
        iter=$((iter + 1))
        if [ "$iter" -gt "$MAX_ITERATIONS_PER_PHASE" ]; then
            exit_reason="max_iterations"; break
        fi
        local now_epoch; now_epoch="$(date +%s)"
        if [ $((now_epoch - START_EPOCH)) -ge "$MAX_WALL_SECONDS" ]; then
            exit_reason="max_wall_seconds"; break
        fi
        local spend
        spend="$(total_spend_in_db "$WORKTREE_DB" "$phase_start_iso")"
        if fp_ge "$spend" "$cap_minus_buffer"; then
            exit_reason="phase_budget_reached  spend=\$$spend"; break
        fi
        # NOTE: unlike the N=1 runners, phase 1 does NOT take a single-file
        # ready_marker shortcut here — with three deliverables that would let
        # phase 1 exit on the FIRST postmortem's marker while two targets are
        # still unbuilt. The soft-sentinel below (strict all-markers + combined
        # test) is the only phase-1 exit. Callers pass sentinel_path="" for
        # phase 1; the guard is kept for any single-deliverable phase.
        if [ -n "$sentinel_path" ] && [ -f "$sentinel_path" ] && grep -qF "$READY_MARKER" "$sentinel_path"; then
            exit_reason="ready_marker_found"; break
        fi
        local cycle_pre
        cycle_pre="$(last_cycle_in_db "$WORKTREE_DB")"
        if ! soak_check_forward_progress "$cycle_pre" "$spend"; then
            log "FATAL: no forward progress (N=${SOAK_NO_PROGRESS_THRESHOLD:-8} iterations with cycle=$cycle_pre spend=\$$spend)"
            exit_reason="no_forward_progress  cycle=$cycle_pre  spend=\$$spend"
            break
        fi
        local tasks_completed_k
        tasks_completed_k="$(soak_extract_tasks_completed_from_log "$LOG")"
        if ! soak_check_task_completion "$tasks_completed_k"; then
            log "FATAL: no task completion (${SOAK_NO_COMPLETION_THRESHOLD:-6} iterations with completed=0/M tasks at budget cap)"
            exit_reason="no_task_completion  last_k=${tasks_completed_k:-unknown}"
            break
        fi
        log "$phase_name iter $iter  cycle=$cycle_pre  spend=\$$spend  cap=\$$cap_usd"

        soak_run_chimera_with_watchdog "$WORKTREE" "$LOG" || \
            log "  watchdog fired for $phase_name iter $iter (treated as iter fail)"
        soak_check_trust_degradation "$trust_baseline" "$phase_name"

        if [ -n "$SOFT_SENTINEL_ALLOWED_FILES" ] && [ -n "$SOFT_SENTINEL_TEST_CMD" ]; then
            if [ "$engines_enabled" = "0" ]; then
                if soak_phase1_deliverable_landed \
                      "$WORKTREE" \
                      "$SOFT_SENTINEL_ALLOWED_FILES" \
                      "$SOFT_SENTINEL_TEST_CMD" \
                      "$READY_MARKER" \
                      "$SOFT_SENTINEL_REQUIRE_ALL_MARKERS"; then
                    exit_reason="soft_sentinel_deliverable_landed"
                    break
                fi
            else
                if soak_phase2_deliverable_landed \
                      "$WORKTREE" \
                      "$SOFT_SENTINEL_ALLOWED_FILES" \
                      "$SOFT_SENTINEL_TEST_CMD"; then
                    exit_reason="soft_sentinel_deliverable_landed"
                    break
                fi
            fi
        fi

        sleep "$COOLDOWN_SECONDS"
    done

    local final_spend
    final_spend="$(total_spend_in_db "$WORKTREE_DB" "$phase_start_iso")"
    log "── $phase_name end: $exit_reason  spend=\$$final_spend iters=$iter ──"
}

# ── phase 1 ────────────────────────────────────────────────────
# Phase-1 soft-sentinel: ALL THREE postmortems present WITH the READY marker
# (strict all-markers mode) AND the combined gate green (all 17 pass → all
# three modules correct). sentinel_path="" so the single-marker shortcut above
# cannot prematurely end phase 1 with two targets unbuilt.
log "phase-1 sentinel targets (OUTPUT deliverables): $ALL_POSTMORTEMS"

SOFT_SENTINEL_ALLOWED_FILES="$ALL_POSTMORTEMS"
SOFT_SENTINEL_TEST_CMD="$GATE_TEST_CMD"
SOFT_SENTINEL_REQUIRE_ALL_MARKERS="1"
log "phase-1 soft-sentinel armed (strict all-markers): files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[combined ×3]"

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "" "0"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""
SOFT_SENTINEL_REQUIRE_ALL_MARKERS=""

# ── phase 2 INBOX — COMMIT the three modules + three postmortems ──────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — Soak v43 phase 2 (commit-only, engines on)

Phase 1 created \`chimera/strcase.py\`, \`chimera/numfmt.py\`, and
\`chimera/seqstats.py\`; the combined gated test passes (17). Phase 2 commits
the three modules and the three postmortems as THREE independent commits.

CHARTER:
  1. SCOPE (locked): the three modules \`chimera/strcase.py\`,
     \`chimera/numfmt.py\`, \`chimera/seqstats.py\` (code) + the three
     postmortems under mind/research/. NOTHING else.
  2. The pre-commit scope check (ADR 0146) is bound to this charter's design
     note; its allowlist is {chimera/strcase.py, chimera/numfmt.py,
     chimera/seqstats.py}. Any other code path — INCLUDING an edit to any
     tests/test_*.py or to chimera/cli.py — is REFUSED.
  3. Re-run \`$GATE_TEST_CMD\` first; confirm 17 passed before committing.
  4. ONE commit per module: stage exactly that module + its postmortem and
     commit with the \`[agent]\` prefix. Do NOT bundle all three into one
     commit; do NOT cite paths absent from the diff (ADR 0122).

## Phase 2 tasks
- [ ] Re-run the combined gated test; confirm 17 passed.
- [ ] Commit 1: stage ONLY \`chimera/strcase.py\` + \`$DELIVERABLE_STRCASE\`; \`[agent]\` commit.
- [ ] Commit 2: stage ONLY \`chimera/numfmt.py\` + \`$DELIVERABLE_NUMFMT\`; \`[agent]\` commit.
- [ ] Commit 3: stage ONLY \`chimera/seqstats.py\` + \`$DELIVERABLE_SEQSTATS\`; \`[agent]\` commit.

Manual-handoff (PR #111): after the commits the runner stops with the branch
left in the worktree. NO auto-push, NO auto-PR, NO auto-merge — the operator
inspects \`git log main..HEAD\`, runs the post-soak gates, and opens any PR by
hand.

OVERSHOOT TRAPS the panel should reject:
  - Editing any test file (refused at commit; falsifies the soak)
  - Committing any code file other than the three targets
  - Committing with the combined gated test still red
  - Bundling all three modules into a single commit (charter wants three)
  - Commit-message rooted-path discipline (ADR 0122)
INBOX_EOF

log "phase-2 INBOX seeded"

# Phase-2 soft-sentinel: all three modules + three postmortems committed; the
# combined gate must pass. The cumulative main..HEAD diff must touch only the
# allowlisted files (+ mind/*), and the combined test forces all three green.
SOFT_SENTINEL_ALLOWED_FILES="$ALL_MODULES $ALL_POSTMORTEMS"
SOFT_SENTINEL_TEST_CMD="$GATE_TEST_CMD"
log "phase-2 soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[combined ×3]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v43.sh complete"
log "  total spend    = \$$TOTAL_SPEND  (cap \$$CHIMERA_ROLLING_HOUR_CAP_USD)"
log "  final cycle    = $FINAL_CYCLE"
log "  elapsed        = $ELAPSED_MIN min"
log "  worktree       = $WORKTREE"
log "  branch         = $BRANCH"
log "  run id         = $CHIMERA_SOAK_RUN_ID"
log "─────────────────────────────────────────────────────────────"

log "── branch commits (expect 3 [agent] commits) ──"
( cd "$WORKTREE" && git log --oneline main..HEAD ) 2>&1 | tee -a "$LOG"

log "── primary gate (post-soak, combined ×3) ──"
( cd "$WORKTREE" && eval "$GATE_TEST_CMD" ) 2>&1 | tee -a "$LOG" || true

log "── verdict-honesty ground truth (test-run ledger) ──"
if [ -f "$WORKTREE/mind/soak/$CHIMERA_SOAK_RUN_ID/test-runs.jsonl" ]; then
    ( cd "$WORKTREE" && jq -s 'any(.[]; .passed==true)' \
        "mind/soak/$CHIMERA_SOAK_RUN_ID/test-runs.jsonl" ) 2>&1 | tee -a "$LOG" || true
else
    log "  (no test-run ledger emitted)"
fi

log "── chimera cost (worktree) ──"
( cd "$WORKTREE" && uv run chimera cost ) 2>&1 | tee -a "$LOG" || true

log "── deliverables ──"
ls -la "$WORKTREE/mind/research/" 2>&1 | tee -a "$LOG"

log ""
log "Review: cd $WORKTREE && git log --oneline main..HEAD   # expect 3 [agent] commits"
log "        CHIMERA_V40_GATE=1 $GATE_TEST_CMD"
log "        git diff main..HEAD --name-only   # expect: 3 modules + 3 postmortems"
log "        jq -s 'any(.[]; .passed==true)' mind/soak/$CHIMERA_SOAK_RUN_ID/test-runs.jsonl"

exit 0
