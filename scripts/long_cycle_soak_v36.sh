#!/usr/bin/env bash
# scripts/long_cycle_soak_v36.sh — micro-soak, single-item classification.
#
# Charter: tests the PR #112 structural hypothesis that the v35
# attempts #1–#4 failures were caused by the multi-item-classification
# task being non-divisible into per-cycle progress under the ACT-phase
# budget. v36 eliminates the multi-item dimension by classifying EXACTLY
# ONE LoCoMo F2 temporal-reasoning regression item (the first by sort
# order, no discretion). Deliverable: one research note paragraph.
# Phase 2 commits the research note only — R1, no code changes.
#
# Post-cascade hardening (PRs #103–#110, #113) is inherited by virtue
# of cloning v34's scaffold: forward-progress watchdog, task-completion
# watchdog, ACT-phase budget enforcement, pre-commit scope check,
# ADR 0141 worktree detector, SQLite thread-affinity fix.
#
# This is NOT a re-run of v35's multi-item temporal-regression
# diagnosis — that chartered question is paused per PR #112's structural
# diagnosis. v36 tests the substrate, not the question.
#
# Atomic-op class: research-note + commit. ≤2 files in the soak's PR.
# Three locked outcomes: CONVERGES / STALLS / CONFABULATES (see design
# note mind/research/v36-micro-soak-design-2026-05-28.md).

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v36.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v36-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v36-$STAMP}"

PHASE1_CAP_USD="${PHASE1_CAP_USD:-5.00}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-5.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.50}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-14400}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

SOAK_TRUST_DROP_THRESHOLD="${SOAK_TRUST_DROP_THRESHOLD:-2}"
SOAK_AUTO_PROMOTE_ON_DEGRADE="${SOAK_AUTO_PROMOTE_ON_DEGRADE:-1}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1
export CHIMERA_ENGINE_SESSION_MODE=1

READY_MARKER="## READY-FOR-REMEDIATION"
LOG="$REPO_ROOT/state/long_cycle_v36_${STAMP}.log"
mkdir -p "$REPO_ROOT/state"
: > "$LOG"

START_EPOCH="$(date +%s)"

# ── helpers ────────────────────────────────────────────────────
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

# ── pre-flight ─────────────────────────────────────────────────
log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v36.sh start — micro-soak (single-item temporal classification)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — investigation)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, commit-only)"
log "  charter        = classify ONE LoCoMo F2 temporal regression item; commit the note"
log "─────────────────────────────────────────────────────────────"

if ! command -v sqlite3 >/dev/null 2>&1; then
    log "FATAL: sqlite3 not on PATH"; exit 2
fi

if [ -d "$WORKTREE" ]; then
    log "FATAL: $WORKTREE already exists. Remove with 'git worktree remove'."
    exit 2
fi

# ── set up worktree ────────────────────────────────────────────
log "syncing local main from origin/main…"
soak_sync_main_from_origin 2>&1 | tee -a "$LOG"
log "creating worktree on branch $BRANCH from main…"
git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"

cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v36-$STAMP" 2>&1 | tee -a "$LOG" || true

WORKTREE_STATE="$WORKTREE/state"
WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"

if [ -f "$REPO_ROOT/state/trust_state.json" ]; then
    cp "$REPO_ROOT/state/trust_state.json" "$WORKTREE_STATE/trust_state.json"
    log "seeded trust state from main (T5)"
fi
if [ -f "$REPO_ROOT/state/tiers.json" ]; then
    cp "$REPO_ROOT/state/tiers.json" "$WORKTREE_STATE/tiers.json"
fi

export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"

# Phase-1 INBOX — v36 atomic charter: classify ONE LoCoMo F2 temporal-
# reasoning regression item. Deliverable is a research-note paragraph.
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v36 phase 1 (investigation only, engines off)

**Chip**: classify ONE LoCoMo F2 temporal-reasoning regression item.
**Atomic op class**: research-note + commit. **≤2 files.**

**Background**: F2 (PR #98) ran hybrid retrieval against LoCoMo's
full 1,986-item corpus. Temporal-reasoning regressed from 45.83%
(F1, no retrieval) to 35.42% (F2, with retrieval). Per the F2
postmortem (mind/research/locomo-f2-retrieval-ablation-2026-05-27.md),
19 items in temporal-reasoning went from F1-right to F2-wrong.

**This chip diagnoses exactly ONE of those 19 items.**

**Three locked hypotheses**:
  - H1 (retrieval-distractor): top-k=8 missed the temporally-relevant
    session because BM25/dense scored distractors above it
  - H2 (context-budget dilution): the timestamp-anchored grounding
    lost weight when retrieval truncated the answerer's context
  - H3 (category-fundamentals): temporal reasoning needs the full
    session sequence to compute time-deltas

**Data sources (read-only)**:
- F1 graded JSONL: `/tmp/locomo-f1/hypotheses.graded.jsonl` (1,986 items)
- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl` (1,986 items)
- F2 postmortem: `mind/research/locomo-f2-retrieval-ablation-2026-05-27.md`
- ADR 0142: `docs/adr/0142-hybrid-retrieval-for-long-horizon.md`

Both JSONLs share schema: `item_id`, `category`, `is_correct`,
`question`, `hypothesis`, `expected_answer`, `sources_used`.

## Phase 1 tasks

- [ ] Use `python3 -c` (NOT `jq` — fields are nested) to find the 19
  items where:
    F1 row.category == "temporal-reasoning" AND F1.is_correct
    AND F2.is_correct == False (same item_id key in both files).
- [ ] **Pick the FIRST item by `item_id` sort order.** No item-selection
  discretion. The point is to test whether the loop converges on a
  single classification, NOT to find the most interesting item.
- [ ] For that one item: inspect the F1 hypothesis, F2 hypothesis,
  gold answer, and (from the question's conv-id prefix) the
  conversation's session count.
- [ ] Classify into H1 / H2 / H3 / H4-other. Write ONE paragraph
  (≤ 6 sentences) explaining the classification.
- [ ] Write the result to
  `mind/research/v36-locomo-temporal-one-item-classification.md`.
  The file MUST end with `## READY-FOR-REMEDIATION`.

  Under that heading, name the item_id and the chosen hypothesis
  (e.g. "Classified `conv-26::qa14` as H1") and explicitly state:
  "R1 — no code change. This chip's atomic deliverable is the
  classification itself; phase 2 commits this research note only."

Do NOT classify more than one item. Do NOT attempt to fan out.
Do NOT propose adapter changes. Do NOT modify ADR 0142.
Do NOT modify any source code or any other file.

CHARTER for phase 2 (v4.112 charter extraction will pass this to the
witness panel from this task text):

  1. SCOPE: ONE file — `mind/research/v36-locomo-temporal-one-item-classification.md`
     (the research note, written in phase 1).
  2. ACTION: commit the research note. No edits to any other file.
  3. The pre-commit scope check (ADR 0146) is locked to R1, so any
     attempt to land code changes will be refused.
  4. NO code modifications. NO ADR edits. NO test additions.
  5. NO modification of any other research note.
  6. Commit message: `[agent]` prefix + the item_id + the chosen
     hypothesis label.

OVERSHOOT TRAPS the panel should reject:

  - **Classifying more than one item** — ONE item only.
  - **Proposing adapter or retrieval code changes** — R1 only.
  - **Modifying ADR 0142** — out of scope; the regression diagnosis
    is the substantive output the soak is supposed to produce, not
    pre-baked.
  - **Citing numbers absent from the F2 data** (confabulation).
  - **Commit message rooted-path discipline** (v4.115 / ADR 0122).
  - **Committing with red tests** (v23 failure mode — though no test
    changes are expected, the suite must still be green).
  - **Lying-by-honesty**: shipping with vague hedging in place of a
    concrete H1/H2/H3/H4 label.

This is the v36 micro-soak. The point is the SHAPE of the deliverable,
not the substance of the diagnosis. Tight scope is what makes the
chip testable.

INBOX_EOF

log "phase-1 INBOX seeded (v36 micro-soak: single-item temporal classification)"

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
            log "FATAL: no forward progress (N=${SOAK_NO_PROGRESS_THRESHOLD:-8} iterations with cycle=$cycle_pre spend=\$$spend)"
            exit_reason="no_forward_progress  cycle=$cycle_pre  spend=\$$spend"
            break
        fi
        # Ladder #6 (v35-postmortem attempt #4, PR #113): additive
        # task-completion signal. Catches the degenerate mode where
        # cycle/spend advance every iter but every ACT phase hits the
        # 240s budget cap with completed=0/N tasks.
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
            # Dispatch by engines flag: phase 1 (engines OFF, no commits)
            # uses file-presence + READY marker; phase 2 uses commit + diff
            # scope + test. Closes the v36-postmortem (PR #117) defect
            # where phase 1 had no real exit-on-deliverable path.
            if [ "$engines_enabled" = "0" ]; then
                if soak_phase1_deliverable_landed \
                      "$WORKTREE" \
                      "$SOFT_SENTINEL_ALLOWED_FILES" \
                      "$SOFT_SENTINEL_TEST_CMD" \
                      "$READY_MARKER"; then
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
INVESTIGATION_DOC="$WORKTREE/$(soak_extract_sentinel_path "$WORKTREE/mind/INBOX.md")"
if [ "$INVESTIGATION_DOC" = "$WORKTREE/" ]; then
    log "FATAL: could not extract sentinel path from $WORKTREE/mind/INBOX.md"; exit 2
fi
log "phase-1 sentinel target: $INVESTIGATION_DOC"
mkdir -p "$WORKTREE/mind/research"

# Phase-1 soft-sentinel: file-presence gate on the OUTPUT deliverable.
# This closes the defect surfaced by PR #117 — INVESTIGATION_DOC above
# points at the F2 INPUT reference doc (first backticked path in INBOX),
# not the output classification the agent writes. The legacy
# `ready_marker_found` exit on INVESTIGATION_DOC is preserved for
# backward compat, but the soft-sentinel below is the real exit path
# for v36-shape soaks.
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v36-locomo-temporal-one-item-classification.md"
SOFT_SENTINEL_TEST_CMD="true"
log "phase-1 soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "$INVESTIGATION_DOC" "0"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── phase 2 INBOX ──────────────────────────────────────────────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v36 phase 2 (commit-only, engines on)

Phase 1's classification is in
`mind/research/v36-locomo-temporal-one-item-classification.md` under
`## READY-FOR-REMEDIATION`. Phase 2 commits that file. Nothing else.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: ONE file — `mind/research/v36-locomo-temporal-one-item-classification.md`.
  2. ACTION: commit the research note. No edits to any other file.
  3. The pre-commit scope check (ADR 0146) is locked to R1, so any
     attempt to land code changes will be refused.
  4. NO code modifications. NO ADR edits. NO test additions.
  5. NO modification of any other research note.
  6. Commit message: `[agent]` prefix + the item_id + the chosen
     hypothesis label (e.g. `[agent] classify conv-26::qa14 as H1`).
     **Do NOT cite rooted paths in the commit message** absent from
     the diff (v4.115 / ADR 0122).

## Phase 2 tasks

- [ ] Re-read the classification from phase 1.
- [ ] Confirm the research note ends with `## READY-FOR-REMEDIATION`
  and contains "R1 — no code change."
- [ ] Stage ONLY `mind/research/v36-locomo-temporal-one-item-classification.md`.
- [ ] Commit with `[agent]` prefix + item_id + hypothesis label.

You are on the soak branch; push is scoped-out via per-worktree
config. After a successful soft-sentinel exit the runner stops
with the branch left in the worktree for manual operator review —
the operator inspects the diff (`git log main..HEAD`), cherry-picks
or discards as appropriate, and opens any resulting PR by hand.
There is NO auto-push, NO auto-PR, NO auto-merge.

OVERSHOOT TRAPS the panel should reject:

  - **Classifying more than one item** — ONE item only.
  - **Proposing adapter or retrieval code changes** — R1 only.
  - **Modifying ADR 0142** — out of scope.
  - **Citing numbers absent from the F2 data** (confabulation).
  - **Commit message rooted-path discipline** (v4.115 / ADR 0122).
  - **Lying-by-honesty**: shipping with vague hedging in place of a
    concrete H1/H2/H3/H4 label.

This is the v36 micro-soak. Single research-note commit; nothing more.

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel: ONE file allowed; no test gate (research-only commit).
# We use `true` for the test command so the gate clears on file presence
# alone — the pre-commit scope check (ADR 0146) enforces the file allow-list
# at commit time.
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v36-locomo-temporal-one-item-classification.md"
SOFT_SENTINEL_TEST_CMD="true"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v36.sh complete"
log "  total spend    = \$$TOTAL_SPEND"
log "  final cycle    = $FINAL_CYCLE"
log "  elapsed        = $ELAPSED_MIN min"
log "  worktree       = $WORKTREE"
log "  branch         = $BRANCH"
log "─────────────────────────────────────────────────────────────"

log "── branch commits ──"
( cd "$WORKTREE" && git log --oneline main..HEAD ) 2>&1 | tee -a "$LOG"

log "── chimera cost (worktree) ──"
( cd "$WORKTREE" && uv run chimera cost ) 2>&1 | tee -a "$LOG" || true

log "── deliverables ──"
ls -la "$WORKTREE/mind/research/" 2>&1 | tee -a "$LOG"

log ""
log "Review: cd $WORKTREE && git log --oneline main..HEAD"
log "        cat mind/research/v36-locomo-temporal-one-item-classification.md"

exit 0
