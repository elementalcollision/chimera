#!/usr/bin/env bash
# scripts/crawl_daily.sh — CRAWL daily driver (ADR 0182, phase 1).
#
# The standing-loop entrypoint for daily autonomous production. Picks the
# next operator-curated backlog spec (mind/backlog/*.md), enforces
# gate-visibility (the spec's gate must be RED on its base — a gate-invisible
# spec is skipped, ADR 0182 / Finding 1), then runs the existing
# real_task_soak.sh against it. The deliverable is a DRAFT PR for batch
# review — manual-handoff, no auto-merge (RUN phase, not CRAWL).
#
# Cadence: one task per run (one/day to begin). Schedule with the operator's
# runner (cron / launchd) in a KEYED environment.
#
# Exit codes:
#   0  a spec was dispatched to the soak (review the resulting branch/PR)
#   1  no actionable spec (empty/all-done backlog) — nothing to do
#   3  candidate specs existed but ALL were gate-invisible / base-errored
#      (skip-and-continue exhausted the queue) — fix the spec(s)
#   2  usage / unexpected error

set -uo pipefail

. "$(dirname "$0")/_soak_common.sh" 2>/dev/null || true
cd "$(dirname "$0")/.." || exit 2
REPO_ROOT="$(pwd)"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

DISPATCH_LOG="${CHIMERA_STATE_DIR:-$REPO_ROOT/state}/crawl_dispatched.txt"
mkdir -p "$(dirname "$DISPATCH_LOG")"
touch "$DISPATCH_LOG"

# Specs already dispatched (awaiting review/merge) are "claimed" so we don't
# re-run them each day. The operator clears a slug from this log — or sets
# `done: true` in the spec — once its PR lands.
CLAIMED="$(paste -sd, "$DISPATCH_LOG" 2>/dev/null || true)"

echo "[crawl] selecting next spec (claimed: ${CLAIMED:-none})"
SPEC_JSON="$(uv run chimera backlog next --check-gate --json --claimed "$CLAIMED" 2>/tmp/crawl_next.err)"
CODE=$?
if [ "$CODE" -ne 0 ]; then
  cat /tmp/crawl_next.err >&2 || true
  case "$CODE" in
    1) echo "[crawl] backlog empty / all done — nothing to dispatch." ;;
    3) echo "[crawl] all candidate specs were gate-invisible / base-errored "
       echo "[crawl] (the picker skipped each) — fix the spec gates." ;;
  esac
  exit "$CODE"
fi

# Pull the soak env out of the JSON without a jq dependency.
eval "$(uv run python - "$SPEC_JSON" <<'PY'
import json, shlex, sys
spec = json.loads(sys.argv[1])
env = spec["env"]
print(f"SLUG={shlex.quote(spec['slug'])}")
for k, v in env.items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"

echo "[crawl] dispatching spec '$SLUG' → real_task_soak.sh"
echo "[crawl]   goal:  $TASK_GOAL"
echo "[crawl]   files: $TASK_FILES"

# Record dispatch BEFORE the soak so a crash can't double-dispatch tomorrow.
echo "$SLUG" >> "$DISPATCH_LOG"

SOAK_OUT="$(mktemp -t crawl-soak.XXXXXX)"
bash "$REPO_ROOT/scripts/real_task_soak.sh" 2>&1 | tee "$SOAK_OUT"
RC=${PIPESTATUS[0]}

# Evidence-first (ADR 0182 Phase 3): record this run's outcome into the
# ledger so RUN-graduation metrics accrue from real history. Parse the
# soak's stable [soak-outcome] line; fall back to a fail record if absent.
OUTCOME_LINE="$(grep '\[soak-outcome\]' "$SOAK_OUT" | tail -1 || true)"
ISSUE_ARG=""
case "$SPEC_JSON" in *'"issue"'*) ISSUE="$(printf '%s' "$SPEC_JSON" | uv run python -c 'import json,sys; print(json.load(sys.stdin).get("issue") or "")')"; [ -n "$ISSUE" ] && ISSUE_ARG="--issue $ISSUE" ;; esac
if [ -n "$OUTCOME_LINE" ]; then
  # shellcheck disable=SC2046  # intentional word-split of key=val tokens
  eval $(printf '%s\n' "$OUTCOME_LINE" | sed -E 's/.*\[soak-outcome\] //; s/([a-z_]+)=([^ ]*)/O_\1="\2"/g')
  uv run chimera crawl record --run-id "${O_run_id:-$RUN_TS}" --slug "$SLUG" \
    --gate "${O_gate:-fail}" --committed "${O_committed:-0}" \
    --cost-usd "${O_cost_usd:-0}" --branch "${O_branch:-}" \
    --base "${O_base:-main}" $ISSUE_ARG 2>&1 | tail -1 || true
else
  echo "[crawl] WARN: no [soak-outcome] line — recording a fail outcome."
  uv run chimera crawl record --run-id "crawl-${SLUG}-$(date -u +%s)" \
    --slug "$SLUG" --gate fail $ISSUE_ARG 2>&1 | tail -1 || true
fi
rm -f "$SOAK_OUT"

# Health snapshot for this run (operational heartbeat; never fails the run).
echo "[crawl] health snapshot:"
uv run chimera health 2>&1 | sed 's/^/[crawl]   /' || true

echo "[crawl] soak finished (rc=$RC). Review the branch/PR; mark the spec"
echo "[crawl] done: true once landed, then: chimera crawl resolve --run-id <id> --disposition merged"
exit 0
