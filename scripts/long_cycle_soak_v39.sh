#!/usr/bin/env bash
# scripts/long_cycle_soak_v39.sh — micro-soak, N=9 FINAL fan-out classification.
#
# Charter: builds on v38's N=10 CONVERGES result (PR #122 runner / PR #124
# postmortem; per-item $0.080 amortized in the charter's pre-registered
# middle band) by classifying the FINAL nine items (#11–#19) of the
# 19-item LoCoMo F2 temporal-reasoning regression set. This CLOSES the
# 19-item diagnosis. Items #1–#5 were classified by v37 (PR #120/#121,
# cherry-picked to main via PR #123) and items #6–#10 by v38 (PR #124
# postmortem, deliverable cherry-picked to main alongside this chip);
# both ranges MUST NOT be re-classified here. Same atomic-op shape:
# research-note + commit, R1, ≤2 files in the soak's PR.
#
# Conservative ladder: N=1 (v36) → N=5 (v37) → N=10 (v38) → N=9 (v39, close).
# v39 finishes the set in one soak rather than a fourth N=10 step plus
# a fifth tail run. The alternative — a full N=19 rewrite — was rejected
# (discards v37+v38's audited paragraphs, harder to audit).
#
# Substrate-discipline check (NEW — two-predecessor skip): the agent must
# correctly SKIP both v37's items #1–#5 AND v38's items #6–#10, picking
# up at item #11. The phase-1 INBOX names both predecessor files as
# READ-ONLY data sources. This is the highest fan-out and highest
# predecessor-integration load in the series.
#
# Cost expectation (honest): the substrate's marginal cost is iter-count-
# dominated and grows with prior-context integration. v39 integrates TWO
# predecessors (vs v38's one), so per-item is expected to drift toward
# $0.10 (above v38's $0.080). Hard cap $1.50 leaves headroom.
#
# Phase-1 sentinel-target fix: v37/v38 inherited a quirk where the
# extracted INVESTIGATION_DOC pointed at the first backticked INBOX entry
# (the F1 INPUT data file), making the legacy `ready_marker_found` exit
# trivial — the soft-sentinel was the real exit. v39 explicitly sets
# INVESTIGATION_DOC to the OUTPUT deliverable so the legacy exit also
# validates the agent's own work. This is a v39-specific correctness
# fix; broader soak-runner template cleanup remains a separate future
# chip.
#
# Post-cascade hardening (PRs #103–#110, #113, #118, #119) is inherited
# by cloning v38's scaffold: forward-progress watchdog, task-completion
# watchdog, ACT-phase budget enforcement, pre-commit scope check,
# ADR 0141 worktree detector, SQLite thread-affinity fix, phase-1
# soft-sentinel, scope-check branch-prefix design-note selection.
#
# Atomic-op class: research-note + commit. ≤2 files in the soak's PR.
# Four locked outcomes: CONVERGES / PARTIAL / STALLS / CONFABULATES (see
# design note mind/research/v39-micro-soak-design-2026-05-28.md).

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v39.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v39-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v39-$STAMP}"

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
LOG="$REPO_ROOT/state/long_cycle_v39_${STAMP}.log"
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
log "long_cycle_soak_v39.sh start — micro-soak (N=9 FINAL fan-out, items #11-#19)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — investigation)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, commit-only)"
log "  charter        = classify NINE LoCoMo F2 temporal regression items #11-#19 (sort-first, skip v37's #1-#5 AND v38's #6-#10); commit the note. CLOSES 19-item diagnosis."
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
    "no-push://disabled-for-soak-v39-$STAMP" 2>&1 | tee -a "$LOG" || true

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

# Phase-1 INBOX — v39 atomic charter: classify NINE FINAL LoCoMo F2
# temporal-reasoning regression items (items #11-#19 by item_id sort,
# closing the 19-item diagnosis; v37 did #1-#5, v38 did #6-#10).
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v39 phase 1 (investigation only, engines off)

**Chip**: classify the FINAL NINE LoCoMo F2 temporal-reasoning
regression items (items #11-#19 by item_id sort order). This
completes the full 19-item diagnosis.
**Atomic op class**: research-note + commit. **≤2 files.**

**Background**: F2 (PR #98) ran hybrid retrieval against LoCoMo's
1,986-item corpus. Temporal-reasoning regressed from 45.83% (F1) to
35.42% (F2). 19 items went from F1-right to F2-wrong. Prior soaks
classified items #1-#10:
- v37 (items #1-#5): H2, H2, H2, H1, H1
- v38 (items #6-#10): H2, H4, H2, H2, H2
v39 classifies the final 9 items, #11-#19.

**This chip classifies items #11 through #19 by item_id sort order.**

**DO NOT re-classify items #1-#10.** Both prior deliverables are on
main (READ ONLY — do not modify):
- `mind/research/v37-locomo-temporal-5-item-classification.md` (items #1-#5)
- `mind/research/v38-locomo-temporal-10-item-classification.md` (items #6-#10)
v39's deliverable is items #11-#19 ONLY.

**Three locked hypotheses** (same as v36/v37/v38):
  - H1 (retrieval-distractor): top-k=8 missed the temporally-relevant
    session because BM25/dense scored distractors above it
  - H2 (context-budget dilution): the timestamp-anchored grounding
    lost weight when retrieval truncated the answerer's context
  - H3 (category-fundamentals): temporal reasoning needs the full
    session sequence to compute time-deltas
  - H4-other: anything that doesn't fit H1/H2/H3 (label explicitly)

**Data sources (read-only)**:
- F1 graded JSONL: `/tmp/locomo-f1/hypotheses.graded.jsonl`
- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl`
- F2 postmortem: `mind/research/locomo-f2-retrieval-ablation-2026-05-27.md`
- v37 prior classification (READ ONLY): `mind/research/v37-locomo-temporal-5-item-classification.md`
- v38 prior classification (READ ONLY): `mind/research/v38-locomo-temporal-10-item-classification.md`
- ADR 0142: `docs/adr/0142-hybrid-retrieval-for-long-horizon.md`

## Phase 1 tasks

- [ ] Use `python3 -c` to find the 19 items where:
    F1 row.category == "temporal-reasoning" AND F1.is_correct
    AND F2.is_correct == False (same item_id key in both files).
- [ ] **Sort by item_id ascending; SKIP the first 10 (already
  classified by v37+v38); take items #11-#19 (the final 9).**
  No item-selection discretion.
- [ ] For EACH of the 9 items, in order:
  - Inspect F1 hypothesis, F2 hypothesis, gold answer
  - Classify into H1 / H2 / H3 / H4-other
  - Append ONE paragraph (≤6 sentences) to the deliverable file
  - Heading pattern: `## Item N: <item_id> → <label>` where N is
    11, 12, ..., 19 (the overall position in the 19-item set)
- [ ] When ALL 9 are classified, append `## READY-FOR-REMEDIATION` with:
  "Classified items <id11>..<id19> as <labels>. R1 — no code change.
   Completes v37+v38 fan-out; all 19 of 19 temporal-reasoning
   regression items now classified across v37+v38+v39."
- [ ] Deliverable file path: `mind/research/v39-locomo-temporal-19-item-classification.md`

Do NOT classify items #1-#10 (already done by v37+v38). Do NOT propose
adapter changes. Do NOT modify ADR 0142 or any prior classification
file. Independently classify each of items #11-#19 from the F1/F2
data — do not infer labels by analogy from v37/v38's distributions.

CHARTER for phase 2:

  1. SCOPE: ONE file — `mind/research/v39-locomo-temporal-19-item-classification.md`.
  2. ACTION: commit the research note. No edits to any other file.
  3. Pre-commit scope check (ADR 0146) is locked to R1; code changes will be refused.
  4. NO code modifications. NO ADR edits. NO test additions.
  5. NO modification of v37's, v38's, or v36's classification files.
  6. Commit message: `[agent]` prefix + "classify items <id11>..<id19> as <labels>".

OVERSHOOT TRAPS the panel should reject:
  - Re-classifying items #1-#10 (v37+v38's work; out of scope)
  - Classifying more or fewer than 9 items but still emitting the marker
  - Proposing adapter or retrieval code changes (R1 only)
  - Modifying ADR 0142 or any prior classification file
  - Citing numbers absent from F2 data (confabulation)
  - Inferring labels by analogy from v37/v38 rather than from items
    #11-#19's own F1/F2 evidence
  - Commit-message rooted-path discipline

INBOX_EOF

log "phase-1 INBOX seeded (v39 micro-soak: N=9 FINAL fan-out, items #11-#19)"

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
            # scope + test. Inherited from PR #118 (phase-1 soft-sentinel
            # closing the v36-postmortem deliverable-path defect).
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
# v39 sentinel-target fix: explicitly set INVESTIGATION_DOC to the OUTPUT
# deliverable, NOT to whatever soak_extract_sentinel_path pulls from the
# first backticked INBOX entry. In v37/v38 the extracted path was the F1
# INPUT JSONL (the first backtick in the data-sources list), making the
# legacy `ready_marker_found` exit trivial — the soft-sentinel (below)
# was the real exit path. v39 closes that gap so the legacy exit also
# validates that the agent has written its own classification file.
# Broader soak-runner template cleanup remains a separate future chip.
INVESTIGATION_DOC="$WORKTREE/mind/research/v39-locomo-temporal-19-item-classification.md"
log "phase-1 sentinel target (v39 explicit fix): $INVESTIGATION_DOC"
mkdir -p "$WORKTREE/mind/research"

# Phase-1 soft-sentinel: file-presence gate on the OUTPUT deliverable.
# Same value as INVESTIGATION_DOC above; both must point at the agent's
# own output, never at a predecessor or an input data file.
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v39-locomo-temporal-19-item-classification.md"
SOFT_SENTINEL_TEST_CMD="true"
log "phase-1 soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "$INVESTIGATION_DOC" "0"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── phase 2 INBOX ──────────────────────────────────────────────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v39 phase 2 (commit-only, engines on)

Phase 1's nine-item classification (items #11-#19) is in
`mind/research/v39-locomo-temporal-19-item-classification.md` under
`## READY-FOR-REMEDIATION`. Phase 2 commits that file. Nothing else.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: ONE file — `mind/research/v39-locomo-temporal-19-item-classification.md`.
  2. ACTION: commit the research note. No edits to any other file.
  3. The pre-commit scope check (ADR 0146) is locked to R1, so any
     attempt to land code changes will be refused.
  4. NO code modifications. NO ADR edits. NO test additions.
  5. NO modification of v37's, v38's, or v36's classification files.
  6. Commit message: `[agent]` prefix + "classify items <id11>..<id19> as
     <labels>" (e.g. `[agent] classify items conv-43::qa31..conv-50::qa48 as H2,H2,H1,H2,H2,H1,H2,H2,H2`).
     **Do NOT cite rooted paths in the commit message** absent from
     the diff (v4.115 / ADR 0122).

## Phase 2 tasks

- [ ] Re-read the classifications from phase 1.
- [ ] Confirm the research note ends with `## READY-FOR-REMEDIATION`
  and contains "R1 — no code change."
- [ ] Confirm nine `## Item N:` paragraphs are present (N = 11,12,…,19).
- [ ] Stage ONLY `mind/research/v39-locomo-temporal-19-item-classification.md`.
- [ ] Commit with `[agent]` prefix + the items + labels summary.

You are on the soak branch; push is scoped-out via per-worktree
config. After a successful soft-sentinel exit the runner stops
with the branch left in the worktree for manual operator review —
the operator inspects the diff (`git log main..HEAD`), cherry-picks
or discards as appropriate, and opens any resulting PR by hand.
There is NO auto-push, NO auto-PR, NO auto-merge.

OVERSHOOT TRAPS the panel should reject:

  - **Re-classifying items #1-#10** (v37+v38's committed work; out of scope).
  - **Classifying more or fewer than 9 items** — exactly 9 (items #11-#19).
  - **Proposing adapter or retrieval code changes** — R1 only.
  - **Modifying ADR 0142** — out of scope.
  - **Modifying v37's, v38's, or v36's classification files** — out of scope.
  - **Citing numbers absent from the F2 data** (confabulation).
  - **Commit message rooted-path discipline** (v4.115 / ADR 0122).
  - **Lying-by-honesty**: shipping with vague hedging in place of
    concrete H1/H2/H3/H4 labels.
  - **Inferring labels by analogy from v37/v38** rather than from
    items #11-#19's own F1/F2 evidence.

This is the v39 FINAL micro-soak. Closes 19-item diagnosis.
Single research-note commit; nothing more.

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel: ONE file allowed; no test gate (research-only commit).
# We use `true` for the test command so the gate clears on file presence
# alone — the pre-commit scope check (ADR 0146) enforces the file allow-list
# at commit time.
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v39-locomo-temporal-19-item-classification.md"
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
log "long_cycle_soak_v39.sh complete"
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
log "        cat mind/research/v39-locomo-temporal-19-item-classification.md"

exit 0
