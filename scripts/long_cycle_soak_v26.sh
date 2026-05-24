#!/usr/bin/env bash
# scripts/long_cycle_soak_v26.sh — focused remediation retry
#
# Design doc: mind/long_cycle_test_plan_v3_2026-05-20.md
#
# Differences from v2 (scripts/long_cycle_remediation.sh):
#   - $5 phase 1 + $5 phase 2 (was $10 + $10) — soak v2 data showed
#     the work was much cheaper than that
#   - CHIMERA_ENGINES_ENABLED=0 in phase 1 — eliminate engine-proposed
#     INBOX displacement (v4.78 would catch it too, belt+suspenders)
#   - Engines back on for phase 2 (chronicle continuity)
#   - Worktree push-block uses per-worktree config (extensions.worktreeConfig)
#     instead of `git remote remove origin` — the v2 approach stripped
#     origin from main's shared config; this scoping doesn't
#   - Trimmed INBOX (4 phase-1 bullets vs v2's 7) — drop sub-agent
#     spawn + wiki_search; they added cost without affecting the
#     verdict
#   - Inherits v4.79 NL artifact validation (no INBOX wording changes
#     needed — the regex picks up the existing "Write ... to ..." form)

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v26.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

# Source provider keys.
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v26-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v26-$STAMP}"

PHASE1_CAP_USD="${PHASE1_CAP_USD:-5.00}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-5.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.50}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-14400}"   # 4h total
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

# v4.95 (ADR 0100 follow-up): mid-soak trust degradation guard.
#   SOAK_TRUST_DROP_THRESHOLD — warn if baseline-current ≥ N (default 2)
#   SOAK_AUTO_PROMOTE_ON_DEGRADE — set to 1 to lift the agent back above T0
SOAK_TRUST_DROP_THRESHOLD="${SOAK_TRUST_DROP_THRESHOLD:-2}"
SOAK_AUTO_PROMOTE_ON_DEGRADE="${SOAK_AUTO_PROMOTE_ON_DEGRADE:-1}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1
export CHIMERA_ENGINE_SESSION_MODE=1   # v4.74 ADR 0092 — session-mode for phase 2

READY_MARKER="## READY-FOR-REMEDIATION"
LOG="$REPO_ROOT/state/long_cycle_v26_${STAMP}.log"
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

# v4.95: read current tier from trust_state.json (0 if missing/unreadable).
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

# v4.95: invoke `chimera trust degrade-check` between cycles. Logs warning
# and (optionally) auto-promotes. Exit code 10 = degraded.
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
log "long_cycle_soak_v26.sh start"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — operator focus)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, session mode)"
log "  per-cycle cap  = \$$CHIMERA_CYCLE_BUDGET_USD"
log "  per-task cap   = \$$CHIMERA_TASK_BUDGET_USD"
log "  rolling60 cap  = \$$CHIMERA_ROLLING_HOUR_CAP_USD"
log "  prerequisites  = v4.78 INBOX priority + v4.79 artifact validation"
log "─────────────────────────────────────────────────────────────"

if ! command -v sqlite3 >/dev/null 2>&1; then
    log "FATAL: sqlite3 not on PATH"; exit 2
fi

if [ -d "$WORKTREE" ]; then
    log "FATAL: $WORKTREE already exists. Remove with 'git worktree remove'."
    exit 2
fi

# ── set up worktree ────────────────────────────────────────────
log "creating worktree on branch $BRANCH from main…"
git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"

cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

# Per-worktree push-block (vs v2's `git remote remove origin` which
# stripped origin from main's shared config). Enables worktree-scoped
# config keys, then overrides the push URL with a deliberately broken
# scheme so any `git push` from the worktree fails fast.
log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v26-$STAMP" 2>&1 | tee -a "$LOG" || true

# State setup
WORKTREE_STATE="$WORKTREE/state"
WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"

# Seed trust state from main — v4.76 added the operator-promote CLI
# but it's still cleaner to inherit T5 directly than walk the tier
# ladder during a 4-hour soak.
if [ -f "$REPO_ROOT/state/trust_state.json" ]; then
    cp "$REPO_ROOT/state/trust_state.json" "$WORKTREE_STATE/trust_state.json"
    log "seeded trust state from main (T5)"
fi
if [ -f "$REPO_ROOT/state/tiers.json" ]; then
    cp "$REPO_ROOT/state/tiers.json" "$WORKTREE_STATE/tiers.json"
fi

export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"

# Phase-1 INBOX — v26 target is v4.116 wiring sub-soak B: call site.
# Atomic op in the v4.116 wiring decomposition. See
# docs/wiring-decomposition-methodology.md for the full plan.
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v26 phase 2 (remediation, engines on)

Phase 1's design is in
`mind/research/v26-call-site-design.md` under
`## READY-FOR-REMEDIATION`. Implement the atomic step.

CHARTER (v4.112 charter extraction will pass this to the witness
panel from this task text):

  1. ONE new block of ~10 lines: the call to `check_charter_file_count(...)` + assignment to a local + `if violations: actresult.charter_file_count_violations = violations; finish_reason = "charter_file_count"`. Place it immediately after the v4.115 `check_commit_message_diff_drift` call at ~line 2033.
  2. SEMANTICS: detector return drives finish_reason. Mirror v4.115's exact priority placement. Charter-file-count fires AFTER commit_message_diff_drift in the cascade.
  3. PATTERN: copy v4.115's call site shape with name swaps. Same try/except envelope (or absence thereof — match exactly).
  4. NO modification of `check_charter_file_count` itself or v4.115's call site (charter #4).
  5. NO escalation, trust, or remediation changes — those are v27/v28/v29.
  6. NO new helper functions — the call is one expression.
  7. The call site must NEVER raise. Wrap in same defensive shape as v4.115 if v4.115 uses one.
  8. NO new dependencies.

## Phase 2 tasks

- [ ] Re-read the design from phase 1.

- [ ] ONE new call site for `check_charter_file_count(...)`, populating `ActResult.charter_file_count_violations` and setting `finish_reason = "charter_file_count"` when the return is non-empty.

- [ ] Add ONE new test asserting that when the detector returns a non-empty list, the ActResult.charter_file_count_violations is populated and the finish_reason is set to 'charter_file_count'.

- [ ] **BEFORE committing**, run `uv run pytest tests/test_charter_file_count.py -q` and
  confirm ALL tests pass. v23 shipped 4 failing test fixtures and
  the deliverable was rejected.

- [ ] Commit your changes with `[agent]` prefix and a one-paragraph
  rationale. **Do NOT cite rooted paths in the commit message**
  that aren't in the diff — v4.115 will fire retroactively in
  test_act.py (ADR 0122 isolates this but charter still requires
  the discipline).

- [ ] Re-run the targeted test post-commit and write the summary
  line into `mind/research/v26-call-site-remediation.md` under `## Test
  results`. The line MUST show `N passed in Xs` with zero failures.

You are on the soak branch; push is scoped-out via a per-worktree
config override. The wiring_coordinator handles push + PR + merge
on a successful soft-sentinel exit.

OVERSHOOT TRAPS the panel should reject:

  - **Commit message rooted-path discipline**: keep the message
    tight to paths actually in the diff. Use "per PR #21" or "per
    ADR 0116" for unrooted references.
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts in the
    remediation doc.
  - Adding the escalation entry (v27's job)
  - Adding the trust delta (v28's job)
  - Adding the remediation hint (v29's job)
  - Refactoring v4.115's call site "for symmetry" (charter #4)
  - Adding a wrapper helper that calls both detectors (charter #6)

This is sub-soak v26 (sub-soak B) of the v4.116 wiring
decomposition. The contract bar is strict.

If you find yourself drifting: STOP. The charter is two files;
nothing more.
INBOX_EOF

# Soft-sentinel params for phase 2 — exit early as soon as a
# charter-clean commit (chimera/core/doctor.py + tests/test_doctor.py)
# AND a passing targeted test are detected. Uses soak_lib.sh v2 which
# auto-allows mind/research/*-remediation.md (v19 retro polish).
SOFT_SENTINEL_ALLOWED_FILES="chimera/core/doctor.py tests/test_doctor.py"
SOFT_SENTINEL_TEST_CMD="uv run pytest tests/test_charter_file_count.py -q 2>&1 | tail -2 | grep -qE '^[0-9]+ passed.*in [0-9.]+s$' && ! uv run pytest tests/test_charter_file_count.py -q 2>&1 | tail -2 | grep -q 'failed'"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

# Disarm so it doesn't leak into any future phase invocations.
SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v26.sh complete"
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

log "── chimera proposers list (worktree) ──"
( cd "$WORKTREE" && uv run chimera proposers list ) 2>&1 | tee -a "$LOG" || true

log "── deliverables ──"
ls -la "$WORKTREE/mind/research/" 2>&1 | tee -a "$LOG"

log ""
log "Review: cd $WORKTREE && git log --oneline main..HEAD"
log "        cat mind/research/v26-call-site-design.md"
log "        cat mind/research/v26-call-site-remediation.md"
log "        uv run pytest tests/test_doctor.py -q"

exit 0
