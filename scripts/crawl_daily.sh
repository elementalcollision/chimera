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

bash "$REPO_ROOT/scripts/real_task_soak.sh"
RC=$?

echo "[crawl] soak finished (rc=$RC). Review the branch/PR; mark the spec"
echo "[crawl] done: true (or remove '$SLUG' from $DISPATCH_LOG) once landed."
exit 0
