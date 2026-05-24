#!/usr/bin/env bash
# scripts/long_cycle_soak_v31.sh — chip-branch-jump detector (sub-soak A)
#
# First sub-soak in the chip-branch-jump prevention composed wiring.
# The papercut: chip sessions sometimes check out their feature branch
# into the OPERATOR's main worktree (e.g. /Users/dave/uberagent) instead
# of a fresh path, polluting main with chip in-progress changes. We've
# hit this 3+ times in the v4.116 / Honcho Phase 3-4 chapter.
#
# Composed wiring (3 layers; this soak ships layer 1 only):
#   1. _check_main_worktree_branch_drift in chimera/core/doctor.py  ← this soak
#   2. Pre-spawn hook refusing worktree creation in an already-occupied path
#   3. Post-commit hook logging structured warning to mind/CHRONICLE.md
#
# Atomic-op class: add-one-check (mirrors v25-v28 single-function shape).
# Sibling template: _check_orphan_worktrees in chimera/core/doctor.py
# (which also reads .git internals to detect a worktree-related issue;
#  the new check reads HEAD branch + cwd instead of mtimes).

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v31.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v31-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v31-$STAMP}"

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
LOG="$REPO_ROOT/state/long_cycle_v31_${STAMP}.log"
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
log "long_cycle_soak_v31.sh start — chip-branch-jump detector (layer 1/3)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — operator focus)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, session mode)"
log "  charter        = add ONE _check_* in chimera/core/doctor.py + ONE test"
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

log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v31-$STAMP" 2>&1 | tee -a "$LOG" || true

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

# Phase-1 INBOX — v31 ships layer 1 of the chip-branch-jump
# prevention composed wiring (first sub-soak in a 3-layer decomposition).
# Atomic op: add-one-check function to chimera/core/doctor.py + one test.
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v31 phase 1 (investigation only, engines off)

**Sub-soak A** of the chip-branch-jump prevention composed wiring.
**Atomic op**: `add-one-check`.
**Target**: Add `_check_main_worktree_branch_drift` to
`chimera/core/doctor.py` + matching test in `tests/test_doctor.py`.

**Background**: Chip sessions sometimes check out their feature branch
into the operator's main worktree (e.g. `/Users/dave/uberagent`)
instead of a fresh path, polluting main with in-progress chip changes.
We've hit this 3+ times. This soak ships the *detector*; layers 2
(pre-spawn hook) and 3 (post-commit logger) come in v32 and v33.

The detection logic: if `cwd == git rev-parse --show-toplevel` (i.e.
we're sitting in the main worktree root) AND the checked-out HEAD
branch is NOT `main`, emit a `warning` (NOT `error` — false-positives
are worse than missed detections; an operator on a feature branch in
the main worktree may have intentionally checked one out).

The template: **`_check_orphan_worktrees`** at
`chimera/core/doctor.py:389` — also a worktree-adjacent detector
that reads `.git/` internals defensively and never raises on benign
input. Copy that shape: defensive try/except, never raises, returns
`CheckResult("name", "ok|warning|error", "message")`.

## Phase 1 tasks (investigation)

- [ ] Read `_check_orphan_worktrees` in `chimera/core/doctor.py` —
  note its `CheckResult` shape, defensive try/except style, and how
  it reads `.git/worktrees/` without subprocess.
- [ ] Read `run_checks()` in the same file to understand the
  registration pattern (you must add ONE call site).
- [ ] Read at least 2 existing tests in `tests/test_doctor.py` for
  the assertion style (CheckResult.status, message contains).
- [ ] Spec the addition. Write to
  `mind/research/v31-doctor-detector-design.md`.
  The file MUST end with a section whose heading is EXACTLY:
  `## READY-FOR-REMEDIATION`

  Under that heading:
    (a) The exact function signature + body to insert.
    (b) The registration line in `run_checks()`.
    (c) The test assertion (one line pseudocode for each of:
        cwd==repo_root+branch=main → ok; cwd==repo_root+branch!=main → warning).

Do NOT modify any source files in phase 1. Investigation only.

## Phase 2 tasks (will be injected by the runner after sentinel)

- ONE new function `_check_main_worktree_branch_drift(repo_root: Path)`
  in `chimera/core/doctor.py`, placed alongside `_check_orphan_worktrees`.
- ONE new line in `run_checks()` calling the new check.
- ONE new test in `tests/test_doctor.py` asserting:
    (a) returns `status='ok'` when checked-out branch IS main
    (b) returns `status='warning'` when checked-out branch is NOT main
        AND cwd matches the main worktree root
- BEFORE committing, run `uv run pytest tests/test_doctor.py -q` and
  confirm ALL tests pass.
- Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** that aren't
  in the diff — v4.115 fires retroactively (ADR 0122 isolates but
  charter expects discipline).
- Re-run tests post-commit, write the result line to
  `mind/research/v31-doctor-detector-remediation.md` under
  `## Test results`.

CHARTER for phase 2 (v4.112 will extract this and pass to witness panel):

  1. SCOPE: ONE new `_check_*` function in
     `chimera/core/doctor.py` + ONE registration line in
     `run_checks()` + ONE test in `tests/test_doctor.py`. 2 files.
  2. SEMANTICS: returns `warning` (NOT `error`) when drift detected;
     `ok` otherwise. Never raises on missing-git / bad cwd / permission denied.
  3. PATTERN: mirror `_check_orphan_worktrees` exactly. Defensive
     try/except wrapping all git/filesystem reads.
  4. NO modification of other existing checks. NO modification of
     `CheckResult` dataclass.
  5. NO new helper functions beyond the single check.
  6. NO new CLI flags, env knobs, or behavior changes elsewhere.
  7. The new check must NEVER raise on benign inputs.
  8. NO new dependencies. Stdlib only.

OVERSHOOT TRAPS the panel should reject:

  - **Implementing layer 2 or 3 of the composed wiring** (v32/v33's
    job). Charter is detector-only.
  - **Adding the check at status='error'** (charter #2). False
    positives must not break startup.
  - **Modifying _check_orphan_worktrees** (charter #4 — it's the
    template, not the target).
  - **Adding a new env knob** like `CHIMERA_BRANCH_DRIFT_ALLOWLIST`
    (charter #6). Defer to a later sub-soak.
  - **Commit message rooted-path discipline** (v4.115 fires retroactively).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts.

This is sub-soak v31 (sub-soak A) of the chip-branch-jump prevention
composed wiring. Single detector function; nothing more.

INBOX_EOF

log "phase-1 INBOX seeded (v31 chip-branch-jump detector, sub-soak A)"

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
        log "$phase_name iter $iter  cycle=$cycle_pre  spend=\$$spend  cap=\$$cap_usd"

        soak_run_chimera_with_watchdog "$WORKTREE" "$LOG" || \
            log "  watchdog fired for $phase_name iter $iter (treated as iter fail)"
        soak_check_trust_degradation "$trust_baseline" "$phase_name"

        if [ -n "$SOFT_SENTINEL_ALLOWED_FILES" ] && [ -n "$SOFT_SENTINEL_TEST_CMD" ]; then
            if soak_phase2_deliverable_landed \
                  "$WORKTREE" \
                  "$SOFT_SENTINEL_ALLOWED_FILES" \
                  "$SOFT_SENTINEL_TEST_CMD"; then
                exit_reason="soft_sentinel_deliverable_landed"
                break
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

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "$INVESTIGATION_DOC" "0"

# ── phase 2 INBOX ──────────────────────────────────────────────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v31 phase 2 (remediation, engines on)

Phase 1's design is in
`mind/research/v31-doctor-detector-design.md` under
`## READY-FOR-REMEDIATION`. Implement the atomic step.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: ONE new `_check_*` function in
     `chimera/core/doctor.py` + ONE registration line in
     `run_checks()` + ONE test in `tests/test_doctor.py`. 2 files.
  2. SEMANTICS: returns `warning` (NOT `error`) when drift detected;
     `ok` otherwise. Never raises.
  3. PATTERN: mirror `_check_orphan_worktrees` exactly. Defensive
     try/except wrapping all git/filesystem reads.
  4. NO modification of other existing checks. NO modification of
     `CheckResult` dataclass.
  5. NO new helper functions beyond the single check.
  6. NO new CLI flags, env knobs, or behavior changes elsewhere.
  7. The new check must NEVER raise on benign inputs.
  8. NO new dependencies. Stdlib only.

## Phase 2 tasks

- [ ] Re-read the design from phase 1.
- [ ] Add `_check_main_worktree_branch_drift(repo_root: Path)` to
  `chimera/core/doctor.py`, alongside `_check_orphan_worktrees`.
- [ ] Add ONE registration line in `run_checks()`.
- [ ] Add ONE test in `tests/test_doctor.py` covering both
  `ok` (branch == main) and `warning` (branch != main) cases.
- [ ] BEFORE committing, run `uv run pytest tests/test_doctor.py -q`
  and confirm ALL tests pass.
- [ ] Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- [ ] Re-run tests post-commit, write the result line to
  `mind/research/v31-doctor-detector-remediation.md` under
  `## Test results`.

You are on the soak branch; push is scoped-out via per-worktree
config. The wiring_coordinator handles push + PR + merge on a
successful soft-sentinel exit.

OVERSHOOT TRAPS the panel should reject:

  - **Implementing layer 2 or 3** of the composed wiring (v32/v33).
  - **status='error'** instead of `warning` (charter #2).
  - **Modifying `_check_orphan_worktrees`** (charter #4 — template).
  - **Adding env knobs** like `CHIMERA_BRANCH_DRIFT_ALLOWLIST` (charter #6).
  - **Commit message rooted-path discipline** (v4.115).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts.

This is sub-soak v31 (chip-branch-jump prevention, layer 1/3).
Single detector function; nothing more.

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel params: 2 files (doctor.py check + registration; test_doctor.py).
SOFT_SENTINEL_ALLOWED_FILES="chimera/core/doctor.py tests/test_doctor.py"
SOFT_SENTINEL_TEST_CMD="uv run pytest tests/test_doctor.py -q 2>&1 | tail -2 | grep -qE '^[0-9]+ passed.*in [0-9.]+s$' && ! uv run pytest tests/test_doctor.py -q 2>&1 | tail -2 | grep -q 'failed'"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v31.sh complete"
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
log "        cat mind/research/v31-doctor-detector-design.md"
log "        cat mind/research/v31-doctor-detector-remediation.md"
log "        uv run pytest tests/test_doctor.py -q"

exit 0
