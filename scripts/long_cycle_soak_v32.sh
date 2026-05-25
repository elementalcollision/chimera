#!/usr/bin/env bash
# scripts/long_cycle_soak_v32.sh — Chip T1.1 from post-baseline priorities
#
# Charter source: mind/research/post-baseline-development-priorities-2026-05-24.md
# (landed via PR #57). Closes Failure mode C: 6 of 30 hypotheses returned
# empty from openai/o4-mini at max_tokens=512 — reasoning-token budget
# exhaustion on deep histories. Expected delta: +6 hypotheses, ~+10pp
# overall on smoke.
#
# Atomic-op class: parameter-tune + add-one-cli-flag.
# Sibling template: existing `--answer-model` flag (chimera/cli.py:654).
# No ADR (parameter tuning, not architecture).

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v32.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v32-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v32-$STAMP}"

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
LOG="$REPO_ROOT/state/long_cycle_v32_${STAMP}.log"
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
log "long_cycle_soak_v32.sh start — Chip T1.1 (token-budget recovery)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — operator focus)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, session mode)"
log "  charter        = bump max_tokens 512→2048 + add --answer-max-tokens flag"
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
    "no-push://disabled-for-soak-v32-$STAMP" 2>&1 | tee -a "$LOG" || true

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

# Phase-1 INBOX — v32 ships Chip T1.1 from post-baseline priorities.
# Atomic op: parameter-tune (max_tokens 512→2048) + add-one-cli-flag
# (--answer-max-tokens). 2 files: chimera/cli.py + tests/test_longmemeval.py.
# NO ADR (parameter tuning, not architecture).
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v32 phase 1 (investigation only, engines off)

**Chip T1.1** from the post-baseline priorities doc (landed via PR #57).
**Atomic op**: `parameter-tune` + `add-one-cli-flag`.
**Target**: Raise `max_tokens` default in `_build_openrouter_answer_fn`
from 512 to 2048; add `--answer-max-tokens N` CLI flag to plumb a
caller-provided value through.

**Background**: The LongMemEval smoke baseline (PR #56, 30 items)
returned 6 EMPTY hypotheses from `openai/o4-mini` due to reasoning-
token budget exhaustion at `max_tokens=512` on deep histories.
Failure mode C in the post-baseline priorities note. Expected delta:
+6 hypotheses (out of 30), category-distributed, ~+10pp overall.

The template: **the existing `--answer-model` flag** (look around
`chimera/cli.py:654` — argparse `add_argument` pattern) and
**`_build_openrouter_answer_fn`** (look around `chimera/cli.py:965`,
the `max_tokens=512` call site is at line ~993).

## Phase 1 tasks (investigation)

- [ ] Read `_build_openrouter_answer_fn` in `chimera/cli.py` —
  note its signature (takes `model_id`), the inner closure that
  calls `openrouter` with `max_tokens=512`, and how the function
  is constructed and returned.
- [ ] Read the `--answer-model` flag definition (around line 654)
  and the parser-build context so the new `--answer-max-tokens`
  flag mirrors the same argparse style.
- [ ] Read `tests/test_longmemeval.py` for the assertion style used
  on the existing answer-fn tests; the new test extends this file.
- [ ] Spec the change. Write to
  `mind/research/v32-token-budget-design.md`. The file MUST end
  with a section whose heading is EXACTLY: `## READY-FOR-REMEDIATION`

  Under that heading:
    (a) The exact edit to `_build_openrouter_answer_fn`'s signature
        and `max_tokens=` argument.
    (b) The exact argparse line for `--answer-max-tokens` and the
        plumbing point at the call site.
    (c) The test assertion (one line of pseudocode covering:
        (i) default-when-flag-absent yields max_tokens=2048,
        (ii) flag-provided value is passed through.)

Do NOT modify any source files in phase 1. Investigation only.

## Phase 2 tasks (will be injected by the runner after sentinel)

- TWO surgical changes in `chimera/cli.py`:
    1. `_build_openrouter_answer_fn(model_id, max_tokens=2048)` —
       signature gains a keyword arg with default 2048 (was hardcoded 512).
    2. New CLI flag `--answer-max-tokens N` on the `evals longmemeval`
       subparser (default 2048, type=int); plumb through to
       `_build_openrouter_answer_fn(args.answer_model, max_tokens=args.answer_max_tokens)`.
- ONE new test in `tests/test_longmemeval.py` covering both default
  (2048 when flag absent) and explicit (provided value passed through).
- BEFORE committing, run `uv run pytest tests/test_longmemeval.py -q`
  and confirm ALL tests pass.
- Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- Re-run tests post-commit, write the result line to
  `mind/research/v32-token-budget-remediation.md` under
  `## Test results`.

CHARTER for phase 2 (v4.112 charter extraction will pass this to the
witness panel from this task text):

  1. SCOPE: TWO surgical edits in `chimera/cli.py` (function signature
     + new CLI flag with plumbing) + ONE test in
     `tests/test_longmemeval.py`. 2 files total.
  2. SEMANTICS: when flag absent → `max_tokens=2048` (was 512).
     When `--answer-max-tokens N` provided → that value is passed
     through verbatim.
  3. PATTERN: argparse style mirrors the existing `--answer-model`
     flag (around line 654). Function signature uses keyword arg
     with default; do NOT change positional args.
  4. NO modification of `_build_sonnet_answer_fn` (different code
     path, not in scope).
  5. NO new ADR (parameter tuning, not architecture).
  6. NO new helper functions; the change is signature + flag + plumbing.
  7. NO retry-with-larger-budget logic (chip is BUDGET BUMP, not
     adaptive retry — adaptive retry is a separate future chip).
  8. NO modification of anything outside `chimera/cli.py` and
     `tests/test_longmemeval.py`. Stdlib + existing deps only.

OVERSHOOT TRAPS the panel should reject:

  - **Adding retry-with-larger-budget adaptive logic** (charter #7 —
    "may recover most" in the priorities doc was a forward-looking
    note, NOT this chip's scope).
  - **Modifying `_build_sonnet_answer_fn`** (charter #4 — different
    code path).
  - **Creating an ADR** (charter #5 — parameter tuning, not arch).
  - **Adding env knobs** (e.g. `CHIMERA_ANSWER_MAX_TOKENS`) — the
    operator-facing surface is the CLI flag only.
  - **Modifying anything outside `chimera/cli.py` and
    `tests/test_longmemeval.py`** (charter #8).
  - **Commit message rooted-path discipline** (v4.115 fires retroactively).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts.

This is Chip T1.1 — first in the post-baseline critical path
(T1.1 → (T1.2 ‖ T1.3) → T1.4 → T2.1). Tight scope is what makes
the chip queue work; don't widen it.

INBOX_EOF

log "phase-1 INBOX seeded (v32 Chip T1.1: token-budget recovery)"

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
# Inbox — Soak v32 phase 2 (remediation, engines on)

Phase 1's design is in
`mind/research/v32-token-budget-design.md` under
`## READY-FOR-REMEDIATION`. Implement the atomic step.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: TWO surgical edits in `chimera/cli.py` (function signature
     + new CLI flag with plumbing) + ONE test in
     `tests/test_longmemeval.py`. 2 files total.
  2. SEMANTICS: when flag absent → `max_tokens=2048` (was 512).
     When `--answer-max-tokens N` provided → that value is passed through.
  3. PATTERN: argparse mirrors the existing `--answer-model` flag.
     Function signature uses keyword arg with default.
  4. NO modification of `_build_sonnet_answer_fn` (different code path).
  5. NO new ADR (parameter tuning, not architecture).
  6. NO new helper functions; change is signature + flag + plumbing.
  7. NO retry-with-larger-budget adaptive logic.
  8. NO modification of anything outside the 2 files.

## Phase 2 tasks

- [ ] Re-read the design from phase 1.
- [ ] Edit `_build_openrouter_answer_fn` signature: add
  `max_tokens=2048` keyword arg; replace hardcoded 512 inside.
- [ ] Add `--answer-max-tokens N` argparse argument; thread
  `args.answer_max_tokens` through the call site.
- [ ] Add ONE test in `tests/test_longmemeval.py` covering default
  (2048) and explicit (provided value) paths.
- [ ] BEFORE committing, run
  `uv run pytest tests/test_longmemeval.py -q` and confirm pass.
- [ ] Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- [ ] Re-run tests post-commit, write the result line to
  `mind/research/v32-token-budget-remediation.md` under `## Test results`.

You are on the soak branch; push is scoped-out via per-worktree
config. The wiring_coordinator handles push + PR + merge on a
successful soft-sentinel exit.

OVERSHOOT TRAPS the panel should reject:

  - **Adding retry-with-larger-budget adaptive logic** (charter #7).
  - **Modifying `_build_sonnet_answer_fn`** (charter #4).
  - **Creating an ADR** (charter #5).
  - **Adding env knobs** instead of / in addition to the CLI flag.
  - **Modifying anything outside `chimera/cli.py` and
    `tests/test_longmemeval.py`** (charter #8).
  - **Commit message rooted-path discipline** (v4.115).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts.

This is Chip T1.1 (post-baseline critical path). Single parameter
bump + single CLI flag; nothing more.

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel: 2 files allowed; targeted test passes.
SOFT_SENTINEL_ALLOWED_FILES="chimera/cli.py tests/test_longmemeval.py"
SOFT_SENTINEL_TEST_CMD="uv run pytest tests/test_longmemeval.py -q 2>&1 | tail -2 | grep -qE '^[0-9]+ passed.*in [0-9.]+s$' && ! uv run pytest tests/test_longmemeval.py -q 2>&1 | tail -2 | grep -q 'failed'"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v32.sh complete"
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
log "        cat mind/research/v32-token-budget-design.md"
log "        cat mind/research/v32-token-budget-remediation.md"
log "        uv run pytest tests/test_longmemeval.py -q"

exit 0
