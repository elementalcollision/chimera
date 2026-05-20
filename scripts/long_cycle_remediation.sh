#!/usr/bin/env bash
# scripts/long_cycle_remediation.sh — interventional long-cycle test
#
# Design doc: mind/long_cycle_test_plan_v2_2026-05-20.md
#
# Workflow:
#   1. git worktree add ../chimera-soak/<stamp> chimera-soak/<stamp>
#   2. cd worktree; git remote remove origin (no push capability)
#   3. fresh state/ DB; seeded mind/ with run-#1 context + focused INBOX
#   4. Phase 1 ($10 cap): investigate degenerate_loop_abort. Watchdog
#      polls for mind/research/loop-abort-investigation.md containing
#      "## READY-FOR-REMEDIATION" — when found, phase ends.
#   5. Phase 2 ($10 cap): remediation. Agent edits chimera/tools/loop_guard.py
#      and tests, commits to the soak branch.
#   6. Post-run: dump diffs + chimera cost / proposers / escalations.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

# Source provider keys.
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# ── configuration ──────────────────────────────────────────────
STAMP="$(date -u +%Y-%m-%d-%H%M)"
BRANCH="chimera-soak/$STAMP"
WORKTREE="${WORKTREE:-$REPO_ROOT/../chimera-soak-$STAMP}"

PHASE1_CAP_USD="${PHASE1_CAP_USD:-10.00}"
PHASE2_CAP_USD="${PHASE2_CAP_USD:-10.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.50}"
MAX_ITERATIONS_PER_PHASE="${MAX_ITERATIONS_PER_PHASE:-200}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-28800}"   # 8h total
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"
export CHIMERA_ENGINES_ENABLED=1
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1
# v4.74 (ADR 0092): session-relative engine routing — direct stress
# test of the routing fix shipped at the end of run #1.
export CHIMERA_ENGINE_SESSION_MODE=1

# Sentinel for phase-1-to-phase-2 transition.
READY_MARKER="## READY-FOR-REMEDIATION"

LOG="$REPO_ROOT/state/long_cycle_v2_2026-05-20.log"
mkdir -p "$REPO_ROOT/state"
: > "$LOG"

START_EPOCH="$(date +%s)"

# ── helpers ────────────────────────────────────────────────────
log() { local ts; ts="$(date '+%H:%M:%S')"; printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG"; }

# Helper: spend in USD over a given window (since START_ISO).
total_spend_in_db() {
    sqlite3 "$1" \
        "SELECT COALESCE(ROUND(SUM(cost_usd), 4), 0.0) FROM api_calls WHERE created_at >= '$2';" \
        2>/dev/null || echo "0.0"
}

last_cycle_in_db() {
    sqlite3 "$1" "SELECT COALESCE(MAX(cycle), 0) FROM api_calls;" 2>/dev/null || echo "0"
}

fp_ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit (a+0 >= b+0) ? 0 : 1 }'; }

# ── pre-flight ─────────────────────────────────────────────────
log "─────────────────────────────────────────────────────────────"
log "long_cycle_remediation.sh start"
log "  branch         = $BRANCH"
log "  worktree       = $WORKTREE"
log "  phase1 cap     = \$$PHASE1_CAP_USD"
log "  phase2 cap     = \$$PHASE2_CAP_USD"
log "  per-cycle cap  = \$$CHIMERA_CYCLE_BUDGET_USD"
log "  per-task cap   = \$$CHIMERA_TASK_BUDGET_USD"
log "  rolling60 cap  = \$$CHIMERA_ROLLING_HOUR_CAP_USD"
log "  session mode   = ON (v4.74 ADR 0092 stress test)"
log "─────────────────────────────────────────────────────────────"

if ! command -v sqlite3 >/dev/null 2>&1; then
    log "FATAL: sqlite3 not on PATH"; exit 2
fi

# If WORKTREE env was set explicitly to an existing dir, reuse it
# (e.g. after a failed bootstrap when we want to recover without
# re-paying the uv install). Otherwise demand a fresh path.
if [ -d "$WORKTREE" ]; then
    if [ -d "$WORKTREE/.git" ] || [ -f "$WORKTREE/.git" ]; then
        log "reusing existing worktree at $WORKTREE"
        BRANCH="$(cd "$WORKTREE" && git branch --show-current)"
        log "  branch picked up from worktree: $BRANCH"
    else
        log "FATAL: $WORKTREE exists but is not a git worktree."
        exit 2
    fi
else
    # ── set up worktree ────────────────────────────────────────
    log "creating worktree on branch $BRANCH from main…"
    git worktree add -b "$BRANCH" "$WORKTREE" main 2>&1 | tee -a "$LOG"
fi

cd "$WORKTREE" || { log "FATAL: cd to worktree failed"; exit 2; }

if git remote | grep -q '^origin$'; then
    log "removing 'origin' remote in worktree (no push possible)…"
    git remote remove origin 2>&1 | tee -a "$LOG" || true
else
    log "origin already removed (worktree reuse)"
fi

# Fresh state dir for the run.
WORKTREE_STATE="$WORKTREE/state"
WORKTREE_DB="$WORKTREE_STATE/chimera.db"
mkdir -p "$WORKTREE_STATE"
# Don't carry the previous run's escalations/scoring/proposer_status —
# fresh start so the test exercises the backfill paths cleanly.
# BUT preserve trust_state.json — a fresh agent at T0 sits in observer
# mode (ACT: LOCKED) burning watchdog iters doing nothing. Carry the
# main repo's earned-T5 trust state so the agent can actually work.
# Surfaced as a soak finding by an earlier run attempt; see post-mortem.
# Only wipe a stale DB if there's no real api_calls history yet (preserves
# the data from an in-progress run when the script is restarted).
if [ -f "$WORKTREE_DB" ]; then
    EXISTING_ROWS="$(sqlite3 "$WORKTREE_DB" "SELECT COUNT(*) FROM api_calls;" 2>/dev/null || echo 0)"
    if [ "${EXISTING_ROWS:-0}" -lt 5 ]; then
        log "wiping nascent worktree DB ($EXISTING_ROWS rows) for a clean start"
        rm -f "$WORKTREE_DB" "$WORKTREE_STATE"/chimera.graph.snapshot.json
    else
        log "preserving existing worktree DB ($EXISTING_ROWS api_calls rows)"
    fi
fi
if [ ! -f "$WORKTREE_STATE/trust_state.json" ] && [ -f "$REPO_ROOT/state/trust_state.json" ]; then
    cp "$REPO_ROOT/state/trust_state.json" "$WORKTREE_STATE/trust_state.json"
    log "seeded trust state from main (T5)"
fi
if [ ! -f "$WORKTREE_STATE/tiers.json" ] && [ -f "$REPO_ROOT/state/tiers.json" ]; then
    cp "$REPO_ROOT/state/tiers.json" "$WORKTREE_STATE/tiers.json"
fi

export CHIMERA_STATE_DIR="$WORKTREE_STATE"
export CHIMERA_MIND_DIR="$WORKTREE/mind"

# Seed mind/ with run-#1 context so the agent has the chronicle +
# the research files to refer to.
log "seeding mind/ with run-#1 context (chronicle + research dir)…"
# CHRONICLE + research already live in the worktree (came from main).
# Just reset the INBOX to the focused phase-1 task.

cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Long-cycle remediation soak (2026-05-20 v2)

This run has ONE focused phase-1 target. Investigate the
`degenerate_loop_abort` hot signature flagged by `chimera escalations
summary` on the 2026-05-20 long-cycle test:

```
×2  tiers=haiku/sonnet        cycles=41→42  last=degenerate_loop_abort
    "Create a glossary of all capability terms used in the matrix as
     a standalone markdown file in mind/research"
```

The loop-detection logic lives at `chimera/tools/loop_guard.py`
(`detect_degenerate_loop`); the call site is in
`chimera/core/act.py` around line 654; the escalation record path
is in `chimera/core/escalation.py`.

## Phase 1: investigation

- [ ] Read `chimera/tools/loop_guard.py` end-to-end. Note the
  signature-window logic, what constitutes a "degenerate" verdict,
  and what variations are admitted. Be explicit about every
  parameter (window size, threshold, normalisation).
- [ ] Read the ACT call site in `chimera/core/act.py` around
  `detect_degenerate_loop(history)`. Map exactly what gets passed
  in and what happens when the verdict comes back True. Identify
  the tool-call history shape.
- [ ] Use the wiki_search + chronicle to find any prior runs of
  the glossary-style task. Reconstruct, as best you can, the tool
  sequence the ACT loop was emitting in cycles 41–42 of the
  2026-05-20 run. (The `task_escalations` table in `state/` from
  run #1 has the signature; the chronicle has narrative context.)
- [ ] Hypothesise: was the guard's verdict CORRECT (the agent
  was actually stuck in a degenerate pattern) or a FALSE POSITIVE
  (the pattern is progressive but looks degenerate by the guard's
  heuristic). Defend the hypothesis with the specific tool-call
  evidence. If you can't reach a confident verdict, say so and
  enumerate what evidence would resolve it.
- [ ] Spawn a sub-agent (different model family — e.g.
  `openrouter/openai/gpt-4-turbo`) to adversarially review your
  verdict. Specifically ask: "Could the opposite verdict also be
  defended from the same evidence? What's the strongest argument
  against my reading?"
- [ ] Write all of the above to
  `mind/research/loop-abort-investigation.md`. The file MUST end
  with a section whose heading is EXACTLY:
  `## READY-FOR-REMEDIATION`
  This sentinel tells the runner to move to phase 2.
  Under that heading, include:
    - One-sentence verdict: false-positive / correct / unresolved
    - A concrete fix proposal (file + function + change shape)
    - Falsification: what test would distinguish the new behaviour
      from the old, written as a failing test case Chimera will
      implement in phase 2.

DO NOT modify any source files in phase 1. Read and write to
`mind/research/` only. Modifying source files (chimera/, tests/,
docs/) is RESERVED for phase 2.
INBOX_EOF

log "phase-1 INBOX seeded"

# Capture start ISO for spend tracking *after* DB exists. Use a
# generously-early timestamp; the fresh DB has no rows so all api_calls
# emitted from here forward are this run.
START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"

# ── phase 1: investigation ─────────────────────────────────────
phase_loop() {
    local phase_name="$1"   # "phase1" | "phase2"
    local cap_usd="$2"
    local cap_minus_buffer
    cap_minus_buffer="$(awk -v c="$cap_usd" -v b="$SAFETY_BUFFER_USD" 'BEGIN { print c - b }')"
    local phase_start_iso="$3"
    local sentinel_path="${4:-}"     # if set, watch for READY_MARKER
    local iter=0
    local exit_reason=""

    log "── $phase_name start: cap=\$$cap_usd safety=\$$SAFETY_BUFFER_USD baseline=$phase_start_iso ──"

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
        # Sentinel check (phase 1).
        if [ -n "$sentinel_path" ] && [ -f "$sentinel_path" ] && grep -qF "$READY_MARKER" "$sentinel_path"; then
            exit_reason="ready_marker_found"; break
        fi
        local cycle_pre
        cycle_pre="$(last_cycle_in_db "$WORKTREE_DB")"
        log "$phase_name iter $iter  cycle=$cycle_pre  spend=\$$spend  cap=\$$cap_usd"

        ( cd "$WORKTREE" && uv run chimera run ) >> "$LOG" 2>&1 || {
            log "  chimera run non-zero exit (continuing — engine skips are normal)"
        }
        sleep "$COOLDOWN_SECONDS"
    done

    local final_spend
    final_spend="$(total_spend_in_db "$WORKTREE_DB" "$phase_start_iso")"
    log "── $phase_name end: $exit_reason  spend=\$$final_spend iters=$iter ──"
}

INVESTIGATION_DOC="$WORKTREE/mind/research/loop-abort-investigation.md"
mkdir -p "$WORKTREE/mind/research"

phase_loop "phase1" "$PHASE1_CAP_USD" "$START_ISO" "$INVESTIGATION_DOC"

# ── phase 2 INBOX ──────────────────────────────────────────────
PHASE2_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
log "phase 2 baseline: $PHASE2_START_ISO"

cat > "$WORKTREE/mind/INBOX.md" <<'INBOX_EOF'
# Inbox — Phase 2 (remediation)

Phase 1 produced `mind/research/loop-abort-investigation.md` with a
verdict and a fix proposal under the `## READY-FOR-REMEDIATION`
section. Now implement it.

## Phase 2: remediation

- [ ] Re-read the verdict + fix proposal in `mind/research/loop-abort-investigation.md`
  under `## READY-FOR-REMEDIATION`. Confirm you still endorse it (a
  short "endorsement check" note at the top of
  `mind/research/loop-abort-remediation.md` documenting either
  agreement, or that you've updated the plan and why).
- [ ] If the verdict was **false-positive:** modify
  `chimera/tools/loop_guard.py` per the proposal. Keep the change
  minimal — surgical edit to the verdict function, not a rewrite.
  Add a regression test to `tests/test_loop_guard.py` that
  reproduces the glossary-task case and asserts the new (admitting)
  behaviour. Run `uv run pytest tests/test_loop_guard.py -q` and
  paste the output into `mind/research/loop-abort-remediation.md`
  under a `## Test results` section.
- [ ] If the verdict was **correct:** modify the ACT loop's
  response to a degenerate_loop_abort verdict in
  `chimera/core/act.py` per the proposal. Most likely: rather than
  hard-aborting, the loop should re-prompt with a "you appear to be
  repeating; please decompose or escalate" hint OR escalate to a
  higher tier OR decompose via the task splitter. Implement the
  simplest of these. Add a test that exercises the new branch in
  `tests/test_act_loop.py` (or wherever ACT tests live).
- [ ] If the verdict was **unresolved:** write the harness that
  would resolve it — a fixture that replays a glossary task at
  controlled tier with controlled history depth, asserts whatever
  loop-guard verdict the operator would expect, and FAILS in the
  current state to motivate the design question.
- [ ] Commit your changes to the current branch with `[agent]`
  prefix and a one-paragraph rationale. Multiple commits are fine.
- [ ] Run the full test suite: `uv run pytest -q
  --ignore=tests/test_graph_store.py --ignore=tests/test_graph_stress.py`.
  Paste the summary line into
  `mind/research/loop-abort-remediation.md` under
  `## Full-suite result`. If anything new fails, do not declare
  done — diagnose and either fix or document.

You are operating on the soak branch (origin removed). You cannot
push. Everything stays local for the operator to review.
INBOX_EOF

log "phase-2 INBOX seeded"

phase_loop "phase2" "$PHASE2_CAP_USD" "$PHASE2_START_ISO" ""

# ── post-run summary ───────────────────────────────────────────
TOTAL_SPEND="$(total_spend_in_db "$WORKTREE_DB" "$START_ISO")"
FINAL_CYCLE="$(last_cycle_in_db "$WORKTREE_DB")"
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))

log "─────────────────────────────────────────────────────────────"
log "long_cycle_remediation.sh complete"
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

log "── chimera escalations summary (worktree) ──"
( cd "$WORKTREE" && uv run chimera escalations summary ) 2>&1 | tee -a "$LOG" || true

log "── deliverables ──"
ls -la "$WORKTREE/mind/research/" 2>&1 | tee -a "$LOG"

log ""
log "When you're back: cd $WORKTREE && git log --oneline main..HEAD"
log "                  cat mind/research/loop-abort-investigation.md"
log "                  cat mind/research/loop-abort-remediation.md"

exit 0
