#!/usr/bin/env bash
# scripts/long_cycle_soak_v34.sh — Chip T1.3 from post-baseline priorities
#
# Charter source: mind/research/post-baseline-development-priorities-2026-05-24.md
# (landed via PR #57). Closes Failure mode B from the smoke baseline
# (PR #56): single-session-preference at 20% accuracy (4/4 wrong).
# Root cause: the model correctly identifies stated user preferences
# (vegetarian, concise responses, etc.) but does NOT honor them when
# generating the answer. The current dialectic prompt asks "answer the
# question" without an explicit instruction to honor stated preferences.
# Expected delta: +40-60pp on single-session-preference.
#
# Sequencing: Chip T1.3 runs AFTER T1.2 lands (PR #64) per PR #57's
# preference for clean per-category regression attribution. T1.2 added
# two cross-session sentences; T1.3 adds one preference-honoring
# sentence. Same surface (_DIALECTIC_PROMPT), additive.
#
# Atomic-op class: extend-prompt-template + add-test + add-adr.
# Sibling templates:
#   - Existing _DIALECTIC_PROMPT constant at chimera/a2a/dialectic.py
#     (extended by T1.2 / PR #64; this chip appends one more sentence)
#   - ADR 0136 (temporal-aware dialectic, the T1.2 ADR — shape sibling)
# 4 files total — within atomic shape.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v34.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v34-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v34-$STAMP}"

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
LOG="$REPO_ROOT/state/long_cycle_v34_${STAMP}.log"
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
log "long_cycle_soak_v34.sh start — Chip T1.3 (preference-aware dialectic)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — operator focus)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, session mode)"
log "  charter        = append one preference-honoring sentence to _DIALECTIC_PROMPT"
log "─────────────────────────────────────────────────────────────"

if ! command -v sqlite3 >/dev/null 2>&1; then
    log "FATAL: sqlite3 not on PATH"; exit 2
fi

if [ -d "$WORKTREE" ]; then
    log "FATAL: $WORKTREE already exists. Remove with 'git worktree remove'."
    exit 2
fi

# ── set up worktree ────────────────────────────────────────────
# NOTE for v35+ template authors: keep the soak_sync_main_from_origin
# call below. It's the load-bearing fix for the v32 post-mortem (PR #61
# body + PR #62) where the worktree forked from a 3-commit-stale local
# main and the agent's diff targeted a since-renamed function. New
# soak runners cloned from this template MUST preserve this sync step.
log "syncing local main from origin/main…"
soak_sync_main_from_origin 2>&1 | tee -a "$LOG"
log "creating worktree on branch $BRANCH from main…"
git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"

cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

log "scoping push-block to this worktree (no impact on main's origin)…"
git config extensions.worktreeConfig true 2>&1 | tee -a "$LOG" || true
git config --worktree remote.origin.pushurl \
    "no-push://disabled-for-soak-v34-$STAMP" 2>&1 | tee -a "$LOG" || true

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

# Phase-1 INBOX — v34 ships Chip T1.3 from post-baseline priorities.
# 4 files: chimera/a2a/dialectic.py, tests/test_dialectic.py,
# docs/adr/0137-preference-aware-dialectic.md, docs/adr/README.md.
# ADR status: Proposed (promotion gate: smoke shows
# single-session-preference moves ≥20pp).
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v34 phase 1 (investigation only, engines off)

**Chip T1.3** from the post-baseline priorities doc (landed via PR #57).
**Atomic op**: extend-prompt-template + add-test + add-adr.
**Target**: Append ONE preference-honoring sentence to `_DIALECTIC_PROMPT`
in `chimera/a2a/dialectic.py` to close Failure mode B
(single-session-preference at 20% in the smoke baseline).

**Background**: LongMemEval smoke baseline (PR #56, 30 items) showed
single-session-preference at 20% accuracy (4/4 wrong). Per-item review
attributed this to Failure mode B: the model correctly identifies
stated user preferences (vegetarian, concise responses, etc.) but
does NOT honor them in the generated answer. The current dialectic
prompt asks "answer the question" without an explicit instruction to
respect stated preferences. Expected delta: +40-60pp on
single-session-preference.

**Sequencing**: T1.2 (temporal-aware) landed in PR #64 and added two
cross-session sentences to the instructions block. This chip (T1.3)
appends ONE more sentence to the SAME instructions block, AFTER T1.2's
additions. Same surface, additive.

The template:
- **`_DIALECTIC_PROMPT`** in `chimera/a2a/dialectic.py` — the
  format-string the dialectic API hands to the model. Post-T1.2 it
  already contains "When the question requires information from
  multiple sessions, integrate facts across the entire history" and
  "When a fact stated in an earlier session is contradicted by a
  later session, prefer the later session."
- **ADR 0133** (dialectic API) is the parent surface; **ADR 0136**
  (temporal-aware dialectic, T1.2) is the immediate sibling and the
  shape template for ADR 0137.
- **`tests/test_dialectic.py`** has the existing tests including
  T1.2's; new test belongs at the END (extend, do NOT create a new
  file).
- **`docs/adr/README.md`** is the index — append a row for 0137,
  bump count from 133 to 134.

## Phase 1 tasks (investigation)

- [ ] Read `_DIALECTIC_PROMPT` in `chimera/a2a/dialectic.py`. Note
  the post-T1.2 state of the initial instructions block. Confirm
  where T1.2's two sentences live and where T1.3's sentence appends
  (after T1.2's, before "Question:").
- [ ] Read at least 2 existing tests in `tests/test_dialectic.py`
  including T1.2's test for prompt-content assertions.
- [ ] Read ADR 0136 at `docs/adr/0136-temporal-aware-dialectic.md`
  to confirm the locked-design table style for the new ADR 0137.
- [ ] Spec the change. Write to
  `mind/research/v34-preference-dialectic-design.md`. The file MUST
  end with a section whose heading is EXACTLY: `## READY-FOR-REMEDIATION`

  Under that heading:
    (a) The exact NEW text to add to `_DIALECTIC_PROMPT`. ONE
        sentence, suggested phrasing:
        "When the user has stated preferences about how they want
         to be answered, honor those preferences in your response."
    (b) The placement: append to the initial instructions block,
        AFTER T1.2's two cross-session sentences, BEFORE the
        "Question:" line. Keep T1.2's sentences and the original
        "Use ONLY the grounding below" / "say so honestly" sentences
        intact and contiguous.
    (c) The test assertion (one line of pseudocode): verify the new
        preference phrasing appears in `build_dialectic_prompt(...)`
        output via substring check.
    (d) The ADR 0137 skeleton: status `Proposed`, locked-design table
        with rows for (Surface, Charter scope, Promotion gate,
        Out of scope). Reference ADR 0133 and ADR 0136 (sibling).
    (e) The README.md edit: one new index row + bump the header
      count `133` to `134`.

Do NOT modify any source files in phase 1. Investigation only.

## Phase 2 tasks (will be injected by the runner after sentinel)

- ONE edit to `chimera/a2a/dialectic.py`: append the preference-
  honoring sentence to the initial instructions block of
  `_DIALECTIC_PROMPT`, AFTER T1.2's cross-session sentences.
- ONE new test in `tests/test_dialectic.py` (at the end) verifying
  the preference sentence appears in `build_dialectic_prompt(...)`
  output.
- ONE new ADR file `docs/adr/0137-preference-aware-dialectic.md`
  (status `Proposed`).
- ONE new index row in `docs/adr/README.md` + bump count 133 → 134.
- BEFORE committing, run `uv run pytest tests/test_dialectic.py -q`
  and confirm ALL tests pass.
- Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- Re-run tests post-commit, write the result line to
  `mind/research/v34-preference-dialectic-remediation.md` under
  `## Test results`.

CHARTER for phase 2 (v4.112 charter extraction will pass this to the
witness panel from this task text):

  1. SCOPE: FOUR files — `chimera/a2a/dialectic.py` (one prompt
     extension), `tests/test_dialectic.py` (one new test),
     `docs/adr/0137-preference-aware-dialectic.md` (new, Proposed),
     `docs/adr/README.md` (one new row + count bump).
  2. SEMANTICS: the extended `_DIALECTIC_PROMPT` still renders via
     `build_dialectic_prompt(ctx, question)`; existing format-string
     placeholders MUST remain valid; existing tests including T1.2's
     MUST still pass.
  3. PATTERN: one new sentence appended after T1.2's two sentences
     in the initial instructions block, before "Question:". Mirror
     the existing prose style (declarative, second-person, no markdown).
  4. NO modification of `_UNKNOWN_PEER_PROMPT` (different code path).
  5. NO modification of T1.2's two cross-session sentences (different
     chip; their wording is locked).
  6. NO new helper functions; the change is one string + one test
     + one ADR + one README row.
  7. NO new CLI flags, env knobs, or behavior changes elsewhere.
  8. The change must NEVER raise on benign inputs (string change only).

OVERSHOOT TRAPS the panel should reject:

  - **Rewriting the entire prompt template** (charter #3 — append
    ONE sentence, do NOT restructure sections).
  - **Modifying T1.2's sentences** (charter #5 — they're locked).
  - **Touching the answer-side prompt** (we only own the assembled
    grounding layer).
  - **Modifying `_UNKNOWN_PEER_PROMPT`** (charter #4).
  - **Adding env knobs** like `CHIMERA_PREFERENCE_DIALECTIC=1` —
    behavior change is unconditional.
  - **ADR status `Accepted`** — must be `Proposed` until promotion
    gate (post-Tier-1 sweep) clears it.
  - **Adding multiple preference-related sentences** — ONE sentence
    only. The PR #57 spec is explicit.
  - **Commit message rooted-path discipline** (v4.115 fires retroactively).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts in the
    remediation doc.

This is Chip T1.3 (post-baseline critical path: T1.1 done →
T1.2 done → T1.3 this soak → T1.4 sweep → T2.1 retrieval). Tight
scope is what makes the chip queue work.

INBOX_EOF

log "phase-1 INBOX seeded (v34 Chip T1.3: preference-aware dialectic)"

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
# Inbox — Soak v34 phase 2 (remediation, engines on)

Phase 1's design is in
`mind/research/v34-preference-dialectic-design.md` under
`## READY-FOR-REMEDIATION`. Implement the atomic step.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: FOUR files — `chimera/a2a/dialectic.py` (one prompt
     extension), `tests/test_dialectic.py` (one new test),
     `docs/adr/0137-preference-aware-dialectic.md` (new, Proposed),
     `docs/adr/README.md` (one new row + count bump 133→134).
  2. SEMANTICS: extended `_DIALECTIC_PROMPT` still renders via
     `build_dialectic_prompt(ctx, question)`; existing format-string
     placeholders remain valid; existing tests including T1.2's
     still pass.
  3. PATTERN: ONE new sentence appended after T1.2's two sentences
     in the initial instructions block, before "Question:".
     Declarative, second-person, no markdown.
  4. NO modification of `_UNKNOWN_PEER_PROMPT`.
  5. NO modification of T1.2's two cross-session sentences (locked).
  6. NO new helpers.
  7. NO new CLI flags or env knobs.
  8. Never raises on benign inputs.

## Phase 2 tasks

- [ ] Re-read the design from phase 1.
- [ ] Append the ONE preference-honoring sentence to
  `_DIALECTIC_PROMPT` in `chimera/a2a/dialectic.py`, after T1.2's
  cross-session sentences.
- [ ] Add ONE new test in `tests/test_dialectic.py` (at end) verifying
  the preference sentence appears in `build_dialectic_prompt(...)`
  output.
- [ ] Create `docs/adr/0137-preference-aware-dialectic.md`
  (Proposed, locked-design table style, references ADR 0133 and ADR 0136).
- [ ] Add ONE new row in `docs/adr/README.md` + bump count 133→134.
- [ ] BEFORE committing, run
  `uv run pytest tests/test_dialectic.py -q` and confirm pass.
- [ ] Commit with `[agent]` prefix + one-paragraph rationale.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- [ ] Re-run tests post-commit, write the result line to
  `mind/research/v34-preference-dialectic-remediation.md` under
  `## Test results`.

You are on the soak branch; push is scoped-out via per-worktree
config. The wiring_coordinator handles push + PR + merge on a
successful soft-sentinel exit.

OVERSHOOT TRAPS the panel should reject:

  - **Rewriting the entire prompt template** (append ONE sentence only).
  - **Modifying T1.2's sentences** (charter #5 — locked).
  - **Touching the answer-side prompt** (out of scope).
  - **Modifying `_UNKNOWN_PEER_PROMPT`** (charter #4).
  - **Adding env knobs** (behavior change is unconditional).
  - **ADR status `Accepted`** (must be `Proposed`).
  - **Adding multiple preference-related sentences** — ONE only.
  - **Commit message rooted-path discipline** (v4.115).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with failure counts.

This is Chip T1.3 (post-baseline tier 1, third of four). Single
prompt extension + test + ADR + README row; nothing more.

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel: 4 files allowed; targeted test passes.
SOFT_SENTINEL_ALLOWED_FILES="chimera/a2a/dialectic.py tests/test_dialectic.py docs/adr/0137-preference-aware-dialectic.md docs/adr/README.md"
SOFT_SENTINEL_TEST_CMD="uv run pytest tests/test_dialectic.py -q 2>&1 | tail -2 | grep -qE '^[0-9]+ passed.*in [0-9.]+s$' && ! uv run pytest tests/test_dialectic.py -q 2>&1 | tail -2 | grep -q 'failed'"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v34.sh complete"
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
log "        cat mind/research/v34-preference-dialectic-design.md"
log "        cat mind/research/v34-preference-dialectic-remediation.md"
log "        uv run pytest tests/test_dialectic.py -q"

exit 0
