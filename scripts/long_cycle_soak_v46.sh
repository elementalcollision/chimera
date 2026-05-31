#!/usr/bin/env bash
# scripts/long_cycle_soak_v46.sh — R3 build, THIRD real feature.
#
# Charter: mind/research/v46-soakreport-design.md. The THIRD real feature
# (capstone of the soak-analysis trio: v44 summary, v45 breakdown). The FIRST
# build to import existing Chimera modules, and the first on the friction-free
# substrate (post-#177 churn fix, #174 witness, #168 over-claim) — expect a
# near-zero-friction convergence (0 witness_rejected, near-0 artifact_missing).
#
# Value: `chimera soak report <run-id>` — one command for the FULL soak health
# view, composing v44's per-cycle iteration table and v45's finish-reason
# breakdown under one headline. This soak lands the isolated module; the CLI
# verb is a separate operator chip.
#
# Target: create ONE new standalone module chimera/soak_report.py that imports
# and composes the two existing pure cores (read-only):
#   - format_report_body(act_rows) -> str        (pure, test-pinned core)
#   - format_soak_report(mind_dir, run_id) -> str (reads act-tools.jsonl)
# so the pre-written test tests/test_soak_report.py (on main, gated, failing)
# passes. Tested DIRECTLY (no CLI) so a regression cannot brick `chimera run`.
#
# Shape (v42 two-phase scaffold, single target):
#   phase 1 (engines OFF, no commits): CREATE the module, run the gated test,
#     iterate to green, write the postmortem with the READY-FOR-REMEDIATION
#     block. The phase-1 soft-sentinel's TEST_CMD is the REAL pytest gate.
#   phase 2 (engines ON, commit-only): commit chimera/soak_report.py + the
#     postmortem. The ADR 0146 scope check (allowlist={chimera/soak_report.py})
#     refuses any other code path, INCLUDING the test or chimera/cli.py.
#
# Honesty: the now-non-dormant gate (PR #163/#164 git-status fallback) validates
# tests_passing / act_cycles / spend_usd in-loop. Numbers are RUN-CUMULATIVE
# (single build → no per-build ambiguity).
#
# Cost: hard cap $3.00 total. Inherits the full hardened scaffold.
#
# Manual-handoff (PR #111): NO auto-push, NO auto-PR, NO auto-merge. The runner
# stops with the branch in the worktree for operator review.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v46.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v46-soakreport-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v46-soakreport-$STAMP}"

PHASE1_CAP_USD="${PHASE1_CAP_USD:-2.50}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.25}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-7200}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

SOAK_TRUST_DROP_THRESHOLD="${SOAK_TRUST_DROP_THRESHOLD:-2}"
SOAK_AUTO_PROMOTE_ON_DEGRADE="${SOAK_AUTO_PROMOTE_ON_DEGRADE:-1}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1
export CHIMERA_ENGINE_SESSION_MODE=1

export CHIMERA_V40_GATE=1
export CHIMERA_SOAK_RUN_ID="v46-soakreport-$STAMP"
export CHIMERA_ACT_BUDGET_SECONDS="${CHIMERA_ACT_BUDGET_SECONDS:-600}"

GATE_TEST_CMD="uv run --extra dev pytest -q tests/test_soak_report.py"

READY_MARKER="## READY-FOR-REMEDIATION"
LOG="$REPO_ROOT/state/long_cycle_v46_${STAMP}.log"
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
log "long_cycle_soak_v46.sh — R3 build, THIRD real feature"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  run id         = $CHIMERA_SOAK_RUN_ID"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — build + test, no commit)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, commit-only)"
log "  hard cap       = \$$CHIMERA_ROLLING_HOUR_CAP_USD (rolling-hour envelope)"
log "  gate test cmd  = $GATE_TEST_CMD"
log "─────────────────────────────────────────────────────────────"

if ! ( cd "$REPO_ROOT" && uv run chimera doctor >/dev/null 2>&1 ); then
    log "WARN: chimera doctor reported issues (continuing; soak runs in worktree)"
fi

if [ -e "$WORKTREE" ]; then
    log "FATAL: worktree path already exists: $WORKTREE"
    exit 2
fi
git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"
cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v46-soakreport-$STAMP" 2>&1 | tee -a "$LOG" || true

# ── re-soak strip (genuine-rebuild knob) ───────────────────────
# The v46 target was operator-landed in #179, so a worktree off main starts
# GREEN with nothing to build. For a genuine RE-BUILD soak (confirming the
# scope_evasion commit-phase fix self-commits cleanly), strip the landed
# module AND its postmortem on the soak branch via a removal commit: phase 1
# then actually rebuilds the module (test goes red → green) and phase 2
# exercises the real commit path. The postmortem MUST be stripped too, else
# its stale READY marker short-circuits the phase-1 sentinel. The strip
# commit is intentionally NOT [agent]-prefixed (it is operator scaffolding,
# not the agent's work). Default off — no behavior change unless set.
if [ -n "${CHIMERA_SOAK_STRIP_TARGETS:-}" ]; then
    log "re-soak: stripping landed targets for genuine rebuild: $CHIMERA_SOAK_STRIP_TARGETS"
    # shellcheck disable=SC2086
    git rm -q $CHIMERA_SOAK_STRIP_TARGETS 2>&1 | tee -a "$LOG" || true
    git commit -q -m "strip v46 targets for re-soak rebuild (operator scaffold; not an [agent] commit)" \
        2>&1 | tee -a "$LOG" || true
fi

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

DELIVERABLE_REL="mind/research/v46-soakreport-postmortem.md"
mkdir -p "$WORKTREE/mind/research"

# ── phase-1 INBOX — CREATE the module, iterate to green, write postmortem ─
cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — Soak v46-soakreport phase 1 (BUILD; engines off, no commits yet)

**Chip**: create ONE new module \`chimera/soak_report.py\` so the pre-written
test passes. You are writing code, not classifying. This is a REAL feature: it
renders the postmortem iteration-vs-spend table from the soak-ledger format.
**Atomic op class**: code + postmortem. **Code goes in ONE NEW file:
\`chimera/soak_report.py\`. Do NOT touch \`chimera/cli.py\`,
\`chimera/core/soak_ledger.py\`, or any other existing source.** (You MAY import
\`from chimera.core.soak_ledger import _read_jsonl\` — but must not modify it.)

## The contract lives in the test (read it; do NOT edit it)

The pre-written test \`tests/test_soak_report.py\` is on main and defines the
exact behavior. READ it to discover the contract. You MUST NOT modify it — the
pre-commit scope check refuses any commit that touches it, and doing so
falsifies the soak.

Run the gated test to see the red state and check progress, EXACTLY as written,
via the shell tool with argv
["uv","run","--extra","dev","pytest","-q","tests/test_soak_report.py"]:

    $GATE_TEST_CMD

Notes:
  - Do NOT prefix the command with \`CHIMERA_V40_GATE=1\`; it is already set and
    inherited, and the argv-only shell tool will REJECT an env-assignment prefix.
  - Use \`uv run --extra dev\` (NOT bare \`python3 -m pytest\`).
  - Pre-implementation: 4 failed. Correct implementation: 4 passed (NOT "6
    skipped").

## Phase 1 tasks — exactly TWO; do them in order

This is a TEST-DRIVEN build. The first task is NOT done until you have RUN the
test and SEEN \`4 passed\`.

- [ ] **Build \`chimera/soak_report.py\` and prove green.** In ONE task: read
  \`tests/test_soak_report.py\` for the EXACT contract — two functions that
  COMPOSE the two existing pure cores (import them at module top:
  \`from chimera.soak_summary import format_iteration_table\` and
  \`from chimera.soak_breakdown import format_finish_reason_breakdown\`):
  \`format_report_body(act_rows)\` (empty → \`""\`; else
  \`"## Iterations\\n\\n" + format_iteration_table(act_rows) + "\\n## Finish
  reasons\\n\\n" + format_finish_reason_breakdown(act_rows)\`) and
  \`format_soak_report(mind_dir, run_id)\` (reads
  \`<mind_dir>/soak/<run_id>/act-tools.jsonl\` via
  \`chimera.core.soak_ledger._read_jsonl\`; empty → \`# Soak <run_id> — no ACT
  records\\n\`; else \`# Soak <run_id> — report (<N> cycles)\\n\\n\` +
  format_report_body(rows)). Do NOT modify soak_summary.py or soak_breakdown.py
  — import them read-only. CREATE the module, run \`$GATE_TEST_CMD\`, read
  failures, EDIT, RUN AGAIN until the output literally contains \`4 passed\`.
  Match the EXACT section headers and newlines; do not approximate.
  **You are NOT done until that command's output shows \`4 passed\`.**
- [ ] **Write the postmortem** \`$DELIVERABLE_REL\` (ONLY after 4 passed) using
  \`mind/postmortems/TEMPLATE-soak-postmortem.md\`. Fill the iteration-vs-spend
  table from the ledgers under \`mind/soak/$CHIMERA_SOAK_RUN_ID/\`, do the
  verdict-honesty cross-check, and end with the \`## READY-FOR-REMEDIATION\`
  block. **Read the numbers — do NOT estimate.** \`act_cycles\` (=
  summarize_run().act_cycles) and \`spend_usd\` (= \`chimera cost\`) are CHECKED
  at write time and are RUN-CUMULATIVE.

## Keep imports module-level

The \`from chimera.core.soak_ledger import _read_jsonl\` import goes at the TOP
of the file. Do NOT put an import inside a function — a function-local import
shadows the module name across the whole function and raises UnboundLocalError
(a pre-commit gate refuses it).

SCOPE (locked): create/edit ONLY \`chimera/soak_report.py\` for code; write ONLY
the postmortem under mind/research/. Do NOT edit the test, do NOT touch
\`chimera/cli.py\`, \`chimera/core/soak_ledger.py\`, any other source, any ADR, or
pyproject.toml. No CLI wiring — this charter is the standalone module only.

OVERSHOOT TRAPS the panel should reject:
  - Editing \`tests/test_soak_report.py\` (read-only; refused at commit)
  - Modifying \`chimera/core/soak_ledger.py\` or any file other than
    \`chimera/soak_report.py\`
  - Claiming the test passes without running the gated command
  - Output not matching the test's exact expected strings
  - A function-local import that shadows a module name
  - Emitting the READY marker with the test still red
  - Estimating act_cycles / spend_usd instead of reading them
INBOX_EOF

log "phase-1 INBOX seeded (v46-soakreport R3 build: chimera/soak_report.py)"

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"

source "$(dirname "$0")/soak_lib.sh"
log "$(soak_lib_version)"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

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
        if [ -n "$sentinel_path" ] && [ -f "$sentinel_path" ] && grep -qF "$READY_MARKER" "$sentinel_path"; then
            exit_reason="ready_marker_found"; break
        fi
        local cycle_pre
        cycle_pre="$(last_cycle_in_db "$WORKTREE_DB")"
        if ! soak_check_forward_progress "$cycle_pre" "$spend"; then
            log "FATAL: no forward progress (cycle=$cycle_pre spend=\$$spend)"
            exit_reason="no_forward_progress  cycle=$cycle_pre  spend=\$$spend"
            break
        fi
        local tasks_completed_k
        tasks_completed_k="$(soak_extract_tasks_completed_from_log "$LOG")"
        if ! soak_check_task_completion "$tasks_completed_k"; then
            log "FATAL: no task completion (completed=0/M at budget cap)"
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
                      "$WORKTREE" "$SOFT_SENTINEL_ALLOWED_FILES" \
                      "$SOFT_SENTINEL_TEST_CMD" "$READY_MARKER"; then
                    exit_reason="soft_sentinel_deliverable_landed"; break
                fi
            else
                # R3 (ADR 0148): harness-executed deterministic commit. The
                # v46 re-soak #2 proved the ADR 0147 gate fires in-loop (58×)
                # but the agent never runs `git commit` — it authors+stages+
                # greens, then spirals into meta-work. Per the agent's own
                # research, ~100% adherence needs "removing the ability to
                # skip": the HARNESS commits, not the agent. Default OFF
                # (knob) so the pure self-commit experiment is unchanged
                # unless the operator opts into harness-commit mode.
                if [ "${CHIMERA_SOAK_AUTOCOMMIT:-0}" = "1" ]; then
                    local _ac_msg="[agent] create chimera/soak_report.py — harness-committed (ADR 0148): agent authored+staged+greened; runner executed the commit (the agent did not run git commit). Re-soak #2 finding."
                    local _ac_status
                    _ac_status="$(cd "$WORKTREE" && CHIMERA_V40_GATE=1 uv run python -c "
import sys
from chimera.soak_autocommit import autocommit_if_ready
print(autocommit_if_ready(
    '.',
    ['chimera/soak_report.py', '$DELIVERABLE_REL'],
    '''$_ac_msg''',
    test_cmd=['uv','run','--extra','dev','pytest','-q','tests/test_soak_report.py'],
))
" 2>>"$LOG")"
                    log "  harness-autocommit: ${_ac_status:-error}"
                fi
                if soak_phase2_deliverable_landed \
                      "$WORKTREE" "$SOFT_SENTINEL_ALLOWED_FILES" \
                      "$SOFT_SENTINEL_TEST_CMD"; then
                    exit_reason="soft_sentinel_deliverable_landed"; break
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
INVESTIGATION_DOC="$WORKTREE/$DELIVERABLE_REL"
log "phase-1 sentinel target (OUTPUT deliverable): $INVESTIGATION_DOC"

SOFT_SENTINEL_ALLOWED_FILES="$DELIVERABLE_REL"
SOFT_SENTINEL_TEST_CMD="$GATE_TEST_CMD"
log "phase-1 soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "$INVESTIGATION_DOC" "0"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── phase 2 INBOX — COMMIT the implementation + postmortem ──────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<INBOX_EOF
# Inbox — Soak v46-soakreport phase 2 (commit-only, engines on)

Phase 1 created \`chimera/soak_report.py\` and the gated test passes. Phase 2
commits the module and the postmortem.

CHARTER:
  1. SCOPE: \`chimera/soak_report.py\` (the implementation) + \`$DELIVERABLE_REL\`
     (the postmortem). NOTHING else.
  2. The pre-commit scope check (ADR 0146) allowlist is {chimera/soak_report.py}.
     Any other code path — INCLUDING tests/test_soak_report.py,
     chimera/core/soak_ledger.py, or chimera/cli.py — is REFUSED.
  3. Re-run \`$GATE_TEST_CMD\` first; confirm 4 passed before committing.
  4. ONE commit. The message MUST begin with the literal token \`[agent]\` as its
     FIRST characters — e.g. \`[agent] create chimera/soak_report.py\`. This is
     not optional: an unprefixed subject does not count and leaves the soak
     unconverged. Do NOT cite paths absent from the diff (ADR 0122).

## Phase 2 tasks
- [ ] Re-run the gated test; confirm 4 passed.
- [ ] Commit the deliverable in ONE step with the **\`git_commit\` tool**:
  call \`git_commit\` with \`message\`=\"create chimera/soak_report.py\" and
  \`paths\`=[\"chimera/soak_report.py\", \"$DELIVERABLE_REL\"]. This single tool
  call stages AND commits AND returns the new HEAD — it IS the whole commit
  step. The \`[agent]\` prefix is added for you. Do NOT also run a bare
  \`git commit\` via shell; do NOT stop after \`git add\` alone.

(If for some reason the \`git_commit\` tool is unavailable, fall back to the
manual flow: \`git add\` the two paths, then a bare \`git commit -m '[agent] ...'\`.)

STAGING IS NOT DONE. \`git add\` only stages — it does NOT create a commit. This
phase is COMPLETE only after \`git commit\` returns AND \`git log --oneline
main..HEAD\` shows your \`[agent]\` commit. If you have staged but not committed,
the task is UNFINISHED: run \`git commit\` now. Do NOT report the task complete on
the strength of a \`git add\` alone — verify the commit exists with \`git log\`
before you stop.

Manual-handoff (PR #111): after the commit the runner stops with the branch in
the worktree. NO auto-push, NO auto-PR, NO auto-merge.

OVERSHOOT TRAPS the panel should reject:
  - Editing the test file or chimera/core/soak_ledger.py (refused at commit)
  - Committing any code file other than chimera/soak_report.py
  - Committing with the gated test still red
  - A commit message that does NOT start with \`[agent]\`
  - Commit-message rooted-path discipline (ADR 0122)
INBOX_EOF

log "phase-2 INBOX seeded"

SOFT_SENTINEL_ALLOWED_FILES="chimera/soak_report.py $DELIVERABLE_REL"
SOFT_SENTINEL_TEST_CMD="$GATE_TEST_CMD"
log "phase-2 soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v46.sh complete"
log "  total spend    = \$$TOTAL_SPEND  (cap \$$CHIMERA_ROLLING_HOUR_CAP_USD)"
log "  final cycle    = $FINAL_CYCLE"
log "  elapsed        = $ELAPSED_MIN min"
log "  worktree       = $WORKTREE"
log "  branch         = $BRANCH"
log "  run id         = $CHIMERA_SOAK_RUN_ID"
log "─────────────────────────────────────────────────────────────"

log "── branch commits (expect 1 [agent] commit) ──"
( cd "$WORKTREE" && git log --oneline main..HEAD ) 2>&1 | tee -a "$LOG"

log "── primary gate (post-soak) ──"
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
log "Review: cd $WORKTREE && git log --oneline main..HEAD   # expect 1 [agent] commit"
log "        CHIMERA_V40_GATE=1 $GATE_TEST_CMD"
log "        git diff main..HEAD --name-only   # expect: chimera/soak_report.py + $DELIVERABLE_REL"
log "        jq -s 'any(.[]; .passed==true)' mind/soak/$CHIMERA_SOAK_RUN_ID/test-runs.jsonl"

exit 0
