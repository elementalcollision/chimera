#!/usr/bin/env bash
# scripts/long_cycle_multi_agent.sh
#
# Long-cycle multi-agent test runner. See mind/long_cycle_test_plan_2026-05-20.md
# for the design. Three cost gates layered:
#
#   per-cycle  $1.50  → CHIMERA_CYCLE_BUDGET_USD          (ADR 0072)
#   per-task   $2.00  → CHIMERA_TASK_BUDGET_USD           (ADR 0079)
#   rolling60m $3.00  → CHIMERA_ROLLING_HOUR_CAP_USD      (ADR 0076)
#   TOTAL RUN  $10.00 → this watchdog (SUM cost_usd since start)
#
# Wall-clock cap: 8h. Iteration cap: 240 cycles.
# Stop early with Ctrl-C — SIGINT lets the in-flight cycle finish.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

# ── configuration ──────────────────────────────────────────────
HARD_TOTAL_CAP_USD="${HARD_TOTAL_CAP_USD:-10.00}"
SAFETY_BUFFER_USD="${SAFETY_BUFFER_USD:-0.50}"
MAX_ITERATIONS="${MAX_ITERATIONS:-240}"
MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-28800}"   # 8h
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"       # between cycles

# Per-layer caps (these gate INSIDE chimera and are also exported).
export CHIMERA_CYCLE_BUDGET_USD="${CHIMERA_CYCLE_BUDGET_USD:-1.50}"
export CHIMERA_TASK_BUDGET_USD="${CHIMERA_TASK_BUDGET_USD:-2.00}"
export CHIMERA_ROLLING_HOUR_CAP_USD="${CHIMERA_ROLLING_HOUR_CAP_USD:-3.00}"

# Engines on (default already), gates on (default), proposer scoring on (default).
export CHIMERA_ENGINES_ENABLED=1
export CHIMERA_ENGINE_GATES_ENABLED=1
export CHIMERA_PROPOSER_SCORING_ENABLED=1

# ── paths ──────────────────────────────────────────────────────
STATE_DIR="${CHIMERA_STATE_DIR:-state}"
DB="$STATE_DIR/chimera.db"
LOG="$STATE_DIR/long_cycle_2026-05-20.log"
mkdir -p "$STATE_DIR"

# Mark the start so we can compute "spend since now" cleanly.
START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"
START_EPOCH="$(date +%s)"

# Signal handling — let in-flight cycles finish.
INTERRUPTED=0
trap 'INTERRUPTED=1; echo "[watchdog] SIGINT received; finishing current cycle then exiting" | tee -a "$LOG"' INT TERM

# Helper: total USD spent since START_ISO via sqlite3 CLI.
total_spend_usd() {
    sqlite3 "$DB" \
        "SELECT COALESCE(ROUND(SUM(cost_usd), 4), 0.0) FROM api_calls WHERE created_at >= '$START_ISO';" \
        2>/dev/null || echo "0.0"
}

# Helper: rolling 60m via the same path the budget module uses.
rolling60_usd() {
    sqlite3 "$DB" \
        "SELECT COALESCE(ROUND(SUM(cost_usd), 4), 0.0) FROM api_calls WHERE created_at >= datetime('now', '-60 minutes');" \
        2>/dev/null || echo "0.0"
}

# Helper: most-recent cycle number.
last_cycle() {
    sqlite3 "$DB" "SELECT COALESCE(MAX(cycle), 0) FROM api_calls;" 2>/dev/null || echo "0"
}

# Floating-point ≥ comparison via awk.
fp_ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit (a+0 >= b+0) ? 0 : 1 }'; }

# ── pre-flight ─────────────────────────────────────────────────
{
    echo "─────────────────────────────────────────────────────────────"
    echo "long_cycle_multi_agent.sh  start=$START_ISO"
    echo "  total cap     = \$$HARD_TOTAL_CAP_USD  (safety buffer \$$SAFETY_BUFFER_USD)"
    echo "  per-cycle cap = \$$CHIMERA_CYCLE_BUDGET_USD"
    echo "  per-task cap  = \$$CHIMERA_TASK_BUDGET_USD"
    echo "  rolling60 cap = \$$CHIMERA_ROLLING_HOUR_CAP_USD"
    echo "  max iters     = $MAX_ITERATIONS"
    echo "  max wall      = $MAX_WALL_SECONDS s"
    echo "─────────────────────────────────────────────────────────────"
} | tee -a "$LOG"

# Cheap preflight: confirm sqlite + chimera both work.
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "[watchdog] FATAL: sqlite3 not on PATH" | tee -a "$LOG"
    exit 2
fi
if [ ! -f "$DB" ]; then
    echo "[watchdog] DB missing — first cycle will create it" | tee -a "$LOG"
fi

# ── main loop ──────────────────────────────────────────────────
iter=0
exit_reason="unknown"

while : ; do
    if [ "$INTERRUPTED" = "1" ]; then
        exit_reason="sigint"
        break
    fi
    iter=$((iter + 1))
    if [ "$iter" -gt "$MAX_ITERATIONS" ]; then
        exit_reason="max_iterations"
        break
    fi

    now_epoch="$(date +%s)"
    elapsed=$((now_epoch - START_EPOCH))
    if [ "$elapsed" -ge "$MAX_WALL_SECONDS" ]; then
        exit_reason="max_wall_seconds"
        break
    fi

    # Pre-cycle spend check — never start a cycle that would push us
    # over the buffered cap, since a cycle can burn up to per-cycle cap.
    spend="$(total_spend_usd)"
    headroom="$(awk -v c="$HARD_TOTAL_CAP_USD" -v s="$spend" -v b="$SAFETY_BUFFER_USD" \
                'BEGIN { printf "%.4f", c - s - b }')"
    if fp_ge "0" "$headroom"; then
        exit_reason="budget_exhausted_before_cycle  spend=\$$spend"
        break
    fi

    rolling="$(rolling60_usd)"
    cycle_pre="$(last_cycle)"

    # Run one cycle. We tee the chimera output into the log but don't
    # bail on non-zero — engine skips are normal.
    ts="$(date '+%H:%M:%S')"
    echo "[$ts] iter $iter  cycle_pre=$cycle_pre  spend=\$$spend  rolling60m=\$$rolling  headroom=\$$headroom" | tee -a "$LOG"

    uv run chimera run >> "$LOG" 2>&1 || {
        rc=$?
        echo "[watchdog]   chimera run exited $rc (continuing — engines often skip)" | tee -a "$LOG"
    }

    # Post-cycle spend check — exit if we crossed the buffered cap.
    spend_post="$(total_spend_usd)"
    if fp_ge "$spend_post" "$(awk -v c="$HARD_TOTAL_CAP_USD" -v b="$SAFETY_BUFFER_USD" 'BEGIN { print c - b }')"; then
        exit_reason="budget_cap_reached  spend=\$$spend_post"
        break
    fi

    # Cooldown between cycles so we don't pin the loop on the same UTC second.
    sleep "$COOLDOWN_SECONDS"
done

# ── post-run summary ───────────────────────────────────────────
final_spend="$(total_spend_usd)"
final_cycle="$(last_cycle)"
{
    echo "─────────────────────────────────────────────────────────────"
    echo "long_cycle_multi_agent.sh  end=$(date -u +%Y-%m-%dT%H:%M:%S)"
    echo "  reason        = $exit_reason"
    echo "  iterations    = $iter"
    echo "  final cycle   = $final_cycle"
    echo "  total spend   = \$$final_spend"
    echo "  elapsed       = $(( ($(date +%s) - START_EPOCH) / 60 )) min"
    echo "─────────────────────────────────────────────────────────────"
} | tee -a "$LOG"

# Operator-facing post-run snapshot via the existing CLI verbs.
echo "" | tee -a "$LOG"
echo "── chimera cost ──" | tee -a "$LOG"
uv run chimera cost 2>&1 | tee -a "$LOG" || true
echo "" | tee -a "$LOG"
echo "── chimera proposers list ──" | tee -a "$LOG"
uv run chimera proposers list 2>&1 | tee -a "$LOG" || true
echo "" | tee -a "$LOG"
echo "── chimera escalations summary ──" | tee -a "$LOG"
uv run chimera escalations summary 2>&1 | tee -a "$LOG" || true

# Exit 0 unless we hit a fatal preflight (those exit earlier).
exit 0
