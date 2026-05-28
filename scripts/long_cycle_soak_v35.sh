#!/usr/bin/env bash
# scripts/long_cycle_soak_v35.sh — LoCoMo temporal-reasoning regression
# investigation. Research-shaped chip (post-v4.115.0 inaugural soak).
#
# Charter source: PR #98 (F2 LoCoMo hybrid-retrieval ablation, MIXED).
# F2 surfaced a real per-category regression: temporal-reasoning fell
# from 45.83% (F1, no retrieval) to 35.42% (F2, with hybrid retrieval),
# a −10.42pp delta that clears ADR 0145's "harms" gate (43.94%) and
# sits well outside any plausible n=96 noise envelope. Every OTHER
# category improved or was in-envelope under retrieval. The asymmetry
# is structural, not redistributive (F1-only-right 19 vs F2-only-right
# 9 on n=96 — net −10 items moved to wrong).
#
# Question: WHY does retrieval hurt this one category? Three locked
# hypotheses to test (H1/H2/H3 in the INBOX). Deliverable is a
# diagnosis + recommendation, NOT a code change by default. If the
# recommendation warrants a small adapter fix, phase 2 may implement
# it within tight scope; otherwise phase 2 is a commit-only step.
#
# Atomic-op class: research-note + optional ADR amendment + optional
# small adapter touch. ≤3 files total.
#
# This is also the post-v4.115.0 inaugural soak — exercises the F2
# infrastructure fixes (persistent asyncio loop, shared httpx.AsyncClient,
# Ollama timeout/retry, PRs #93/#94/#96/#97) and the chip-branch-jump
# prevention contract (ADR 0141) in actual agent-loop context. The
# chip's success criterion has two layers:
#   1. Substantive — produces a defensible diagnosis (H1/H2/H3 or other).
#   2. Operational — soak completes cleanly, exercising the new code.

set -uo pipefail

# shellcheck disable=SC1091
. "$(dirname "$0")/_soak_common.sh"
soak_refuse_concurrent "long_cycle_soak_v35.sh" || exit $?
soak_install_killgroup_trap

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/v35-$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-v35-$STAMP}"

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
LOG="$REPO_ROOT/state/long_cycle_v35_${STAMP}.log"
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
log "long_cycle_soak_v35.sh start — LoCoMo temporal-regression investigation (post-v4.115.0 inaugural soak)"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD (engines OFF — operator focus)"
log "  phase2 cap     = \$$PHASE2_CAP_USD (engines ON, session mode)"
log "  charter        = diagnose F2's −10.42pp temporal-reasoning regression (H1/H2/H3)"
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
    "no-push://disabled-for-soak-v35-$STAMP" 2>&1 | tee -a "$LOG" || true

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

# Phase-1 INBOX — v35 investigates the LoCoMo temporal-reasoning
# regression surfaced by F2 (PR #98). Research-shaped chip: deliverable
# is a diagnosis + recommendation, NOT a code change. Phase 2 commits
# the research note and (only if recommended by phase 1) lands a small
# adapter touch — ≤3 files total either way.
cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Soak v35 phase 1 (investigation only, engines off)

**Chip**: LoCoMo temporal-reasoning regression investigation.
**Atomic op class**: research-note + (optional, only if phase 1
recommends) small adapter touch + ADR amendment. **≤3 files.**

**Background**: F2 (PR #98, merged at `cf75258`) ran hybrid retrieval
(`--hybrid-retrieval --retrieval-top-k 8`, BM25 + dense Ollama bge-m3)
against the full 1,986-item LoCoMo corpus. Headline: **+10.02pp**
overall, three categories improving by 7–20pp, single-hop in-envelope,
**temporal-reasoning regressing by −10.42pp** (45.83% → 35.42%). The
regression clears ADR 0145's harms gate (43.94%) and is well outside
any plausible n=96 noise σ. Per-item flip analysis confirmed the
regression is structural (19 F1-only-right vs 9 F2-only-right on n=96
→ net −10 items moved from right to wrong), not redistributive.

Every OTHER category improved or was in-envelope under retrieval; the
asymmetry is the open question. The F2 note recommended this
investigation explicitly (§"Recommended follow-up").

**Three locked hypotheses** to test:

  - **H1 (retrieval-distractor)**: top-k=8 misses the temporally-relevant
    session(s) because BM25/dense scores rank distractor sessions above
    them. Falsifiable: for regressed items, check whether the gold-
    answer session is in the top-8 retrieval set or got displaced.
  - **H2 (context-budget displacement)**: retrieval substantially shortens
    the answerer's context, so the timestamp-anchored grounding from
    ADR 0136 (PR #69 "Today's date" + per-session date headers) loses
    proportional weight against the answerer's pretraining priors.
    Falsifiable: compare F1 vs F2 input-token counts on regressed items;
    check whether the grounding headers are still present at the top.
  - **H3 (category-fundamentals)**: temporal reasoning needs the full
    session sequence to compute time-deltas (X happened on date A, Y
    happened on date B, so Y was N days after X). Any truncation
    breaks the chain regardless of which sessions survive. Falsifiable:
    compare the gold answers' temporal-reasoning patterns between
    items that did vs didn't regress.

Other hypotheses are allowed and should be classified as "H4-other"
with a label, not forced into H1/H2/H3.

**Data sources** (read-only, no modification):

- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl`
  (1,986 lines, includes per-item retrieval metadata via the
  `sources_used` field if present)
- F1 graded JSONL: PR #91's reference — likely
  `/tmp/chimera-locomo-f1/hypotheses.graded.jsonl` or similar; if not
  found, regenerate by re-running the grader against F1's hypothesis
  JSONL (no answerer cost; ~$0.10 grader-only).
- F2 research note: `mind/research/locomo-f2-retrieval-ablation-2026-05-27.md`
- ADR 0142 (hybrid retrieval, has §Cross-benchmark check from F2):
  `docs/adr/0142-hybrid-retrieval-for-long-horizon.md`
- ADR 0145 (LoCoMo noise envelope, has the harms gate of 43.94%):
  `docs/adr/0145-locomo-noise-envelope.md`
- LoCoMo corpus: `data/locomo10.json` (or `/tmp/locomo/locomo10.json`)
- LoCoMo adapter: `chimera/evals/locomo.py`
- Hybrid retrieval helper: `chimera/evals/hybrid_retrieval.py`
  (`select_top_k_sessions`, BM25, RRF math, embedder backends)

## Phase 1 tasks (investigation, no source changes)

- [ ] **Identify the regressed items** — diff F1 vs F2 graded JSONLs,
  filter to `category == "temporal-reasoning"` and `F1.is_correct ==
  True AND F2.is_correct == False`. Expect ~19 items.
- [ ] **For each regressed item, classify into H1/H2/H3/H4-other** —
  inspect the item's `question`, gold `answer`, F1 hypothesis, F2
  hypothesis, and (if available) F2's top-k retrieval set. Where the
  retrieval set is not logged, re-run retrieval offline using
  `chimera.evals.hybrid_retrieval.select_top_k_sessions(...)` against
  the conversation's sessions to identify which sessions would have
  been picked. Read-only — do not modify any files in `chimera/`.
- [ ] **Tally** — classification table with H1/H2/H3/H4-other counts.
  At least one item per class should have an illustrative quote
  (question + the mechanism evidence) in the research note.
- [ ] **Recommendation** — pick one of:
   - **R1**: No code change. Document the diagnosis, recommend
     accepting the temporal-reasoning trade-off as a known property
     of top-k=8 hybrid retrieval on LoCoMo; defer (or pre-charter)
     a follow-up chip for the next exploratory step.
   - **R2**: Small adapter fix (e.g., reserve a top-k slot for the
     most-recent session, or bias retrieval toward chronological
     coverage). Specify the exact change in ≤30 LOC, the test to
     add, and the expected directional outcome.
   - **R3**: Larger redesign required — out of scope for this soak;
     phase 2 will commit the diagnosis only.
- [ ] **Write the design note** to
  `mind/research/v35-locomo-temporal-regression-design.md`. MUST end
  with a section whose heading is EXACTLY: `## READY-FOR-REMEDIATION`

  Under that heading:
    (a) The recommendation (R1 / R2 / R3) — one paragraph.
    (b) If R2: the exact code change (file + LOC range + new text),
        the exact new test, and the soft-sentinel allowed-files list
        the phase 2 charter should use.
    (c) If R1 or R3: explicit "no code edits in phase 2" — the
        deliverable is the research note + (optionally) an additive
        subsection to ADR 0142 §Cross-benchmark check with the
        hypothesis classification.

Do NOT modify any files outside `mind/research/` in phase 1.
Investigation only.

## Phase 2 tasks (commit + optional small fix; will be re-injected)

The phase-2 INBOX will be re-injected after phase 1 lands the design
note. The shape will depend on phase 1's R1/R2/R3 recommendation —
the runner uses the SOFT_SENTINEL_ALLOWED_FILES list below as the
default (research note + ADR 0142 amendment), but the phase-2 INBOX
can override if R2 expanded scope.

CHARTER for phase 2:

  1. SCOPE: ≤3 files total. Default set: research-note (phase 1's
     design doc, finalized + maybe phase-2 results section), ADR 0142
     amendment (additive subsection only — DO NOT touch existing
     content), and at most ONE code+test if R2.
  2. SEMANTICS: any code change must be additive (e.g., a new helper
     function or an opt-in flag); existing F1 numbers and ADR 0142
     §Cross-benchmark check substantive content remain unchanged.
  3. PATTERN: research-first. Even if R2 is picked, the code change
     is bounded by the design note's specified LOC and test.
  4. NO modification of `chimera/evals/locomo.py` adapter shape
     (existing fields, ctor params, summarize_results) — additive
     only if R2 demands.
  5. NO modification of ADR 0142's §Decision, §Consequences,
     §Alternatives — only an additive new subsection under
     §Consequences titled "Temporal-reasoning regression diagnosis
     (v35 soak)" if warranted.
  6. NO modification of ADR 0145 or F1/F3 numbers.
  7. NO new CLI flags or env knobs unless R2 design note specifies
     and gates them off-by-default.
  8. The change must NEVER raise on benign inputs.

OVERSHOOT TRAPS the panel should reject:

  - **Reclassifying the F2 verdict** — MIXED stands; this chip
    diagnoses, doesn't relitigate.
  - **Restructuring `chimera/evals/hybrid_retrieval.py`** — only
    additive helpers if R2.
  - **Modifying `select_top_k_sessions`'s signature** — additive
    parameter at most, default preserves prior behaviour.
  - **Touching ADR 0142's §Decision** or §Consequences.Positive — only
    add a new "Temporal-reasoning regression diagnosis" subsection.
  - **Adding a config knob without an opt-out** — defaults must
    preserve F2 behaviour bit-for-bit.
  - **Re-running the full LoCoMo sweep** to validate R2 — that's a
    follow-up chip's job, not this soak's.
  - **Commit message rooted-path discipline** (v4.115 / ADR 0122).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with classification gaps unmarked.

This is the post-v4.115.0 inaugural soak. Beyond the substantive
deliverable, success means: (a) Chimera completes the 2-phase loop
cleanly, (b) the F2 infrastructure fixes (persistent loop, shared
httpx, Ollama timeout/retry) hold up under sustained agent activity,
(c) the chip-branch-jump prevention contract (ADR 0141) is exercised
correctly. All three are validated by completion.

INBOX_EOF

log "phase-1 INBOX seeded (v35: LoCoMo temporal-regression investigation)"

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
# Inbox — Soak v35 phase 2 (commit + optional small fix; engines on)

Phase 1's design is in
`mind/research/v35-locomo-temporal-regression-design.md` under
`## READY-FOR-REMEDIATION`. Read its R1/R2/R3 recommendation and act
accordingly.

CHARTER (v4.112 charter extraction will pass this to the witness panel):

  1. SCOPE: ≤3 files total. Default set (for R1 or R3 recommendations):
     research note (finalize phase 1's design doc with any phase-2
     results section), `docs/adr/0142-hybrid-retrieval-for-long-horizon.md`
     (additive subsection only — DO NOT touch existing content). If
     R2, add at most ONE code+test pair specified in the design.
  2. SEMANTICS: any code change must be additive; existing F1/F2/F3
     numbers and ADR 0142 §Cross-benchmark check substantive content
     remain unchanged.
  3. PATTERN: research-first. Even if R2 is picked, the code change is
     bounded by the design note's specified LOC and test name.
  4. NO modification of `chimera/evals/locomo.py` adapter shape — only
     additive helpers if R2 demands.
  5. NO modification of ADR 0142's §Decision, §Consequences (existing
     subsections), or §Alternatives — only an additive new subsection
     under §Consequences titled "Temporal-reasoning regression diagnosis
     (v35 soak)" if warranted.
  6. NO modification of ADR 0145 or F1/F2/F3 numbers.
  7. NO new CLI flags or env knobs unless R2 design specifies them and
     gates them off-by-default.
  8. Never raises on benign inputs.

## Phase 2 tasks

- [ ] Re-read the design from
  `mind/research/v35-locomo-temporal-regression-design.md`.
- [ ] If R1 or R3: NO code edits. Append the diagnosis (hypothesis
  classification table + one-paragraph synthesis) as an additive
  subsection in ADR 0142's §Consequences titled
  "Temporal-reasoning regression diagnosis (v35 soak)".
- [ ] If R2: implement the design's specified change in ONE file
  (likely `chimera/evals/hybrid_retrieval.py`) + ONE new test
  (likely `tests/test_hybrid_retrieval.py`). LOC bounded by the
  design note. Then add the additive ADR 0142 subsection as above.
- [ ] BEFORE committing, run targeted tests:
  - Always: `uv run pytest tests/test_hybrid_retrieval.py tests/test_locomo.py -q`
  - If R2 added a new test file or helper test, include it.
  Confirm all pass.
- [ ] Commit with `[agent]` prefix + one-paragraph rationale that
  names: (a) the R1/R2/R3 recommendation taken, (b) the dominant
  hypothesis (H1/H2/H3/H4-other) from the classification table.
  **Do NOT cite rooted paths in the commit message** absent from
  the diff (v4.115 / ADR 0122).
- [ ] Re-run tests post-commit, write the result line to
  `mind/research/v35-locomo-temporal-regression-remediation.md`
  under `## Test results`.

You are on the soak branch; push is scoped-out via per-worktree
config. The wiring_coordinator handles push + PR + merge on a
successful soft-sentinel exit.

OVERSHOOT TRAPS the panel should reject:

  - **Reclassifying the F2 verdict** — MIXED stands; this chip
    diagnoses, doesn't relitigate.
  - **Restructuring `chimera/evals/hybrid_retrieval.py`** — only
    additive helpers if R2.
  - **Modifying `select_top_k_sessions`'s signature** — additive
    parameter at most, default preserves prior behaviour.
  - **Touching ADR 0142's §Decision** or existing §Consequences
    subsections — only ADD a new "Temporal-reasoning regression
    diagnosis (v35 soak)" subsection.
  - **Adding a config knob without an opt-out** — defaults must
    preserve F2 behaviour bit-for-bit.
  - **Re-running the full LoCoMo sweep** to validate R2 — that's a
    follow-up chip's job, not this soak's.
  - **Commit message rooted-path discipline** (v4.115).
  - **Committing with red tests** (v23 failure mode).
  - **Lying-by-honesty**: shipping with classification gaps unmarked
    or a recommendation that doesn't match the data in the table.

Post-v4.115.0 inaugural soak. Beyond substantive output, success
means clean two-phase loop completion under the new infrastructure
(persistent asyncio loop / shared httpx / Ollama retry / chip-branch-
jump prevention).

INBOX_EOF

log "phase-2 INBOX seeded"

# Soft-sentinel: default 3-file set (research note + ADR amendment +
# remediation log). If phase 1 picks R2 with a small adapter touch, the
# panel may extend this list per the design note, but the default
# preserves the research-only shape. Test cmd targets the modules
# that R2 would touch; passes vacuously if no code edits.
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v35-locomo-temporal-regression-design.md mind/research/v35-locomo-temporal-regression-remediation.md docs/adr/0142-hybrid-retrieval-for-long-horizon.md"
SOFT_SENTINEL_TEST_CMD="uv run pytest tests/test_hybrid_retrieval.py tests/test_locomo.py -q 2>&1 | tail -2 | grep -qE '^[0-9]+ passed.*in [0-9.]+s$' && ! uv run pytest tests/test_hybrid_retrieval.py tests/test_locomo.py -q 2>&1 | tail -2 | grep -q 'failed'"
log "soft-sentinel armed: files=[$SOFT_SENTINEL_ALLOWED_FILES] test=[$SOFT_SENTINEL_TEST_CMD]"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" "" "1"

SOFT_SENTINEL_ALLOWED_FILES=""
SOFT_SENTINEL_TEST_CMD=""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_soak_v35.sh complete"
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
log "        cat mind/research/v35-locomo-temporal-regression-design.md"
log "        cat mind/research/v35-locomo-temporal-regression-remediation.md"
log "        uv run pytest tests/test_hybrid_retrieval.py tests/test_locomo.py -q"

exit 0
