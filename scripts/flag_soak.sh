#!/usr/bin/env bash
# scripts/flag_soak.sh — keyed FLAG-graduation A/B harness (ADR 0184 / 0185).
#
# Toggles ONE feature flag (named by env FLAG, e.g. CHIMERA_TOOL_PREFILTER) OFF
# (0) vs ON (1) across runs of the SAME spec and scores the cost/token delta the
# flag is responsible for — the evidence ADR 0184/0185 gate a default-on flip on.
#
# This is the FIX for the inconclusive first attempt (mind/research/
# flag-soak-0184-first-attempt-2026-06-19.md), which had two confounds:
#   1. UNEQUAL OUTCOMES — the OFF arm failed the gate while ON passed, so the
#      delta measured "OFF gave up early," not the flag. → Here a trial pair
#      counts ONLY when BOTH its OFF and ON arms reach gate=pass; any pair where
#      either arm fails is DISCARDED (logged, not scored) and the run continues.
#   2. SINGLE SAMPLE — n=1 with large run-to-run variance. → Here AB_TRIALS
#      (default 3) trial pairs are run and the delta is reported per-pair AND as
#      the MEDIAN over the valid (both-green) pairs.
#   3. WRONG SIGNAL GRANULARITY — total-token delta buries the prefilter lever
#      (tool-definition input tokens) under conversation/file context. → Here the
#      INPUT-token delta is surfaced specifically, alongside total tokens/cost.
#
# The two arms within a pair differ ONLY in the flag's value; identical spec,
# base SHA, model, gates, and caps. qwen-led by default so the lead rung is held
# constant across arms (overridable).
#
# Required env:
#   FLAG       name of the boolean flag env var to toggle, e.g.
#              CHIMERA_TOOL_PREFILTER (0184) or CHIMERA_COMPLEXITY_ROUTING (0185).
#   AB_SPEC    path to the spec both arms run (a mind/ab/*.md probe or a backlog
#              spec). Its frontmatter supplies TASK_GOAL/TASK_FILES/TASK_TEST/
#              TASK_BASE via the SAME parser the CRAWL picker uses.
# Optional env:
#   AB_TRIALS              trial PAIRS to attempt (default 3). Each pair = one OFF
#                          run + one ON run of the spec.
#   CHIMERA_ACT_FORCE_MODEL model both arms are pinned to (default
#                          qwen/qwen3.7-max — qwen-led). Held identical across
#                          arms so the flag is the only difference.
#   FLAG_OFF / FLAG_ON     the OFF/ON values (default 0 / 1).
#   AB_BASE / TASK_BASE    base ref; pinned to a SHA up front so a concurrent
#                          merge can't move the ref mid-run (ab_battery pattern).
#   TASK_DRYRUN=1          resolve + print the full plan (flag, spec, trials,
#                          arms, base SHA) and exit WITHOUT launching any soak.
#   Memory guard / any real_task_soak.sh knob (CHIMERA_RUN_RSS_CAP_MB,
#   PHASE1_CAP_USD, MAX_WALL_SECONDS, …) passes through to every arm unchanged —
#   the whole environment is inherited by real_task_soak.sh.
#
# Manual-handoff: NOTHING is pushed, merged, or pruned. Each arm stops with its
# branch in its own worktree; the worktrees are printed for review. Discard them
# yourself with `git worktree prune` when done.
#
# Exit codes: 0 the harness ran (review the report — note valid_pairs may be 0);
#             2 usage / spec error.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
REPO_ROOT="$(pwd)"
# shellcheck disable=SC1091
if [ -f .env ]; then set -a; . ./.env; set +a; fi

: "${FLAG:?FLAG is required (name of the boolean flag env var to toggle, e.g. CHIMERA_TOOL_PREFILTER)}"
: "${AB_SPEC:?AB_SPEC is required (path to the spec both arms run)}"
[ -f "$AB_SPEC" ] || { echo "flag_soak: spec not found: $AB_SPEC" >&2; exit 2; }

# qwen-led by default — held identical across arms so the flag is the ONLY
# difference (the first attempt held the model constant too; we keep that).
FORCE_MODEL="${CHIMERA_ACT_FORCE_MODEL:-qwen/qwen3.7-max}"
FLAG_OFF="${FLAG_OFF:-0}"
FLAG_ON="${FLAG_ON:-1}"

# Trial PAIRS to attempt. Multi-trial is the variance fix (≥3 → median).
TRIALS="${AB_TRIALS:-3}"
[ "$TRIALS" -ge 1 ] 2>/dev/null || TRIALS=3

# Resolve the spec's TASK_* via the same parser the CRAWL picker / ab_soak use,
# so a spec that works for the daily loop works here verbatim. Fails closed on an
# invalid spec (the parser reports errors instead of raising).
eval "$(uv run python - "$AB_SPEC" <<'PY'
import shlex, sys
from pathlib import Path
from chimera.core.backlog import parse_spec
spec = parse_spec(Path(sys.argv[1]))
if not spec.valid:
    sys.stderr.write("flag_soak: invalid spec: " + "; ".join(spec.errors) + "\n")
    print("AB_SPEC_INVALID=1")
    raise SystemExit(0)
print(f"SPEC_SLUG={shlex.quote(spec.slug)}")
for k, v in spec.task_env().items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
[ "${AB_SPEC_INVALID:-0}" = "1" ] && exit 2

# Pin the base ref to a SHA ONCE, up front, and pass it to every arm as
# TASK_BASE (ab_battery pattern). A multi-trial flag soak runs for hours; if it
# tracked the moving "main" ref and someone merged mid-run, in-flight worktrees
# (branched from the old tip) would see the new commits as a phantom diff and the
# phase-2 deliverable sentinel would never fire — spinning each affected arm to
# its wall ceiling. A fixed SHA immunises the whole run from concurrent merges.
AB_BASE="${AB_BASE:-${TASK_BASE:-main}}"
BASE_SHA="$(git -C "$REPO_ROOT" rev-parse --verify "$AB_BASE" 2>/dev/null || echo "$AB_BASE")"
export TASK_BASE="$BASE_SHA"

STATE_DIR="${CHIMERA_STATE_DIR:-$REPO_ROOT/state}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
REPORT="$STATE_DIR/flag_soak_${FLAG}_${SPEC_SLUG}_${STAMP}.txt"
mkdir -p "$STATE_DIR"

echo "=== flag_soak: ${FLAG} OFF(${FLAG_OFF}) vs ON(${FLAG_ON}) — ${SPEC_SLUG} ==="
echo "  flag    : $FLAG   (off=$FLAG_OFF on=$FLAG_ON)"
echo "  spec    : $AB_SPEC"
echo "  goal    : $TASK_GOAL"
echo "  files   : $TASK_FILES"
echo "  test    : ${TASK_TEST:-<full suite>}"
echo "  model   : $FORCE_MODEL (qwen-led; identical across both arms)"
echo "  base    : ${AB_BASE} @ ${BASE_SHA} (pinned; immune to concurrent merges)"
echo "  trials  : ${TRIALS} pair(s) → $(( TRIALS * 2 )) soaks max ($(( TRIALS )) OFF + $(( TRIALS )) ON)"
echo "  scoring : both-arm gate=pass REQUIRED per pair; cost-delta over valid pairs (median)"
echo "  report  : $REPORT"
echo "─────────────────────────────────────────────────────────────"

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    echo
    echo "(dryrun) PLAN — nothing will launch, no spend, no ledger writes."
    echo "(dryrun)   For each of ${TRIALS} trial pair(s): run the spec OFF then ON,"
    echo "(dryrun)   keep the pair ONLY if BOTH arms reach gate=pass, else DISCARD it."
    for trial in $(seq 1 "$TRIALS"); do
        echo "(dryrun) ── trial ${trial}/${TRIALS} ──"
        for arm in off on; do
            [ "$arm" = "off" ] && val="$FLAG_OFF" || val="$FLAG_ON"
            sfx="flag-${arm}-t${trial}"
            wt="$REPO_ROOT/../chimera-soak-flag-${SPEC_SLUG}-${arm}-t${trial}-${STAMP}"
            echo "(dryrun)   arm ${arm}: ${FLAG}=${val}  CHIMERA_ACT_FORCE_MODEL=${FORCE_MODEL}"
            echo "(dryrun)            RUN_ID_SUFFIX=${sfx}"
            echo "(dryrun)            WORKTREE=${wt}"
            echo "(dryrun)            TASK_BASE=${BASE_SHA}  DB=<worktree>/state/chimera.db"
        done
    done
    echo "(dryrun) Per valid pair: chimera cost-delta --baseline <off_db> --treatment <on_db>"
    echo "(dryrun)   → total-token, INPUT-token (the prefilter lever), and cost deltas."
    echo "(dryrun) Aggregate: report each valid pair + the MEDIAN delta; report valid_pairs/attempted."
    echo "(dryrun) no soak launched, no spend."
    exit 0
fi

# run_arm ARM TRIAL → echoes "gate db_path branch run_id" for that arm's soak.
#   ARM is "off"|"on"; the flag is exported at the arm's value for THIS run only.
#   Distinct RUN_ID_SUFFIX + WORKTREE per (arm, trial) so branches, worktrees,
#   ledger slugs, and DBs never collide. The whole environment (memory guard,
#   caps, walls) is inherited by real_task_soak.sh — only FLAG + the
#   run-disambiguators are set per-arm.
run_arm() {
    local arm="$1" trial="$2" val
    [ "$arm" = "off" ] && val="$FLAG_OFF" || val="$FLAG_ON"
    local sfx="flag-${arm}-t${trial}"
    local wt="$REPO_ROOT/../chimera-soak-flag-${SPEC_SLUG}-${arm}-t${trial}-${STAMP}"
    local db="$wt/state/chimera.db"
    local out; out="$(mktemp -t flag-soak-"${arm}".XXXXXX)"
    echo "── ${FLAG}=${val} (arm '${arm}' trial ${trial}) → CHIMERA_ACT_FORCE_MODEL=${FORCE_MODEL} ──" >&2
    # export the flag at the arm's value for the duration of THIS soak only.
    CHIMERA_ACT_FORCE_MODEL="$FORCE_MODEL" \
    RUN_ID_SUFFIX="$sfx" \
    WORKTREE="$wt" \
    env "${FLAG}=${val}" \
        bash "$REPO_ROOT/scripts/real_task_soak.sh" 2>&1 | tee "$out" >&2
    local line; line="$(grep '\[soak-outcome\]' "$out" | tail -1 || true)"
    rm -f "$out"
    if [ -z "$line" ]; then
        echo "fail $db - flag-${arm}-t${trial}-noline"
        return
    fi
    # Parse key=val tokens off the stable [soak-outcome] line into O_* vars.
    eval "$(printf '%s\n' "$line" | sed -E 's/.*\[soak-outcome\] //; s/([a-z_]+)=([^ ]*)/O_\1="\2"/g')"
    # shellcheck disable=SC2154  # O_* are assigned by the eval above (sed → O_<key>=<val>)
    local gate="${O_gate:-fail}" branch="${O_branch:-}" rid="${O_run_id:-flag-${arm}-t${trial}}"
    echo "$gate $db $branch $rid"
}

# Per-pair delta rows are accumulated here for the python aggregation step:
#   "<trial> <total_delta> <total_pct> <input_delta> <input_pct> <cost_delta> <cost_pct>"
ROWS="$(mktemp -t flag-soak-rows.XXXXXX)"
trap 'rm -f "$ROWS"' EXIT

VALID=0
ATTEMPTED=0
PAIR_LOG=""   # human-readable per-pair lines for the report

for trial in $(seq 1 "$TRIALS"); do
    echo "════════ trial ${trial}/${TRIALS} ════════" >&2
    ATTEMPTED=$((ATTEMPTED + 1))

    read -r OFF_GATE OFF_DB OFF_BRANCH OFF_RUNID <<<"$(run_arm off "$trial")"
    read -r ON_GATE  ON_DB  ON_BRANCH  ON_RUNID  <<<"$(run_arm on  "$trial")"

    # BOTH-ARM-GREEN REQUIRED. A pair counts ONLY if BOTH arms reached
    # gate=pass; otherwise it confounds the delta (the first-attempt failure
    # mode) — DISCARD it, log it, and continue.
    if [ "$OFF_GATE" != "pass" ] || [ "$ON_GATE" != "pass" ]; then
        echo "── trial ${trial} DISCARDED: off=${OFF_GATE} on=${ON_GATE} (both must pass) ──" >&2
        PAIR_LOG="${PAIR_LOG}$(printf 'trial %s  DISCARDED (off=%s [%s] on=%s [%s]) — not scored\n' \
            "$trial" "$OFF_GATE" "$OFF_RUNID" "$ON_GATE" "$ON_RUNID")"
        continue
    fi

    # Both green → score the flag's effect with the deterministic, key-free
    # cost-delta analyzer over the two arms' api_calls DBs. Capture total, INPUT
    # (the prefilter lever), and cost deltas from the JSON.
    if [ ! -f "$OFF_DB" ] || [ ! -f "$ON_DB" ]; then
        echo "── trial ${trial} DISCARDED: missing DB (off=$OFF_DB on=$ON_DB) ──" >&2
        PAIR_LOG="${PAIR_LOG}$(printf 'trial %s  DISCARDED (db missing) — not scored\n' "$trial")"
        continue
    fi

    delta_json="$(uv run chimera cost-delta --baseline "$OFF_DB" --treatment "$ON_DB" --json 2>/dev/null)"
    if [ -z "$delta_json" ]; then
        echo "── trial ${trial} DISCARDED: cost-delta produced no output ──" >&2
        PAIR_LOG="${PAIR_LOG}$(printf 'trial %s  DISCARDED (cost-delta failed) — not scored\n' "$trial")"
        continue
    fi

    # Pull the fields we report. input_delta = ON.input − OFF.input (the
    # TOOL_PREFILTER lever the first attempt could not isolate).
    read -r TOT_D TOT_P INP_D INP_P COST_D COST_P <<<"$(
        printf '%s' "$delta_json" | uv run python -c '
import json, sys
d = json.load(sys.stdin)
b, t = d["baseline"], d["treatment"]
inp_d = t["input_tokens"] - b["input_tokens"]
inp_p = round((inp_d / b["input_tokens"] * 100.0), 2) if b["input_tokens"] else 0.0
print(d["token_delta"], d["token_pct"], inp_d, inp_p, d["cost_delta"], d["cost_pct"])
' 2>/dev/null)"
    [ -n "$TOT_D" ] || { echo "── trial ${trial} DISCARDED: delta parse failed ──" >&2; continue; }

    VALID=$((VALID + 1))
    printf '%s %s %s %s %s %s %s\n' "$trial" "$TOT_D" "$TOT_P" "$INP_D" "$INP_P" "$COST_D" "$COST_P" >> "$ROWS"
    echo "── trial ${trial} VALID: total ${TOT_D} tok (${TOT_P}%)  input ${INP_D} tok (${INP_P}%)  cost \$${COST_D} (${COST_P}%) ──" >&2
    PAIR_LOG="${PAIR_LOG}$(printf 'trial %s  VALID  total %+d tok (%s%%)  input %+d tok (%s%%)  cost $%+0.4f (%s%%)  [off=%s on=%s; off=%s on=%s]\n' \
        "$trial" "$TOT_D" "$TOT_P" "$INP_D" "$INP_P" "$COST_D" "$COST_P" "$OFF_BRANCH" "$ON_BRANCH" "$OFF_RUNID" "$ON_RUNID")"
done

# ── report (python aggregation: per-pair + median over valid pairs) ──────
{
echo "=== flag_soak report: ${FLAG} — ${SPEC_SLUG} (${STAMP}) ==="
echo "flag : ${FLAG}  (off=${FLAG_OFF} on=${FLAG_ON})"
echo "spec : ${AB_SPEC}"
echo "goal : ${TASK_GOAL}"
echo "model: ${FORCE_MODEL} (qwen-led; identical across arms)"
echo "base : ${AB_BASE} @ ${BASE_SHA}"
echo
echo "Both-arm gate=pass required per pair (a pair where either arm fails is"
echo "DISCARDED — it confounds the delta; see the 2026-06-19 first attempt)."
echo
echo "Per-pair (delta = treatment[ON] − baseline[OFF]):"
printf '%s' "$PAIR_LOG"
echo
echo "valid_pairs / attempted: ${VALID} / ${ATTEMPTED}"
echo

VALID="$VALID" ATTEMPTED="$ATTEMPTED" FLAG="$FLAG" uv run python - "$ROWS" <<'PY'
import os, statistics, sys

rows = []
try:
    with open(sys.argv[1]) as fh:
        for line in fh:
            p = line.split()
            if len(p) != 7:
                continue
            rows.append((int(p[0]), int(p[1]), float(p[2]), int(p[3]),
                         float(p[4]), float(p[5]), float(p[6])))
except FileNotFoundError:
    rows = []

valid = int(os.environ.get("VALID", "0"))
flag = os.environ.get("FLAG", "FLAG")

if not rows:
    print("AGGREGATE: no valid (both-green) pairs — INCONCLUSIVE.")
    print("  Re-run with more trials (AB_TRIALS) or a more deterministic spec;")
    print("  a flag soak is only valid when both arms reach the same outcome.")
    raise SystemExit(0)


def med(xs):
    return statistics.median(xs)


tot_d = med([r[1] for r in rows]); tot_p = med([r[2] for r in rows])
inp_d = med([r[3] for r in rows]); inp_p = med([r[4] for r in rows])
cost_d = med([r[5] for r in rows]); cost_p = med([r[6] for r in rows])

print(f"AGGREGATE over {len(rows)} valid pair(s) — MEDIAN delta (ON − OFF):")
print(f"  total tokens : {tot_d:+,.0f} ({tot_p:+.2f}%)")
print(f"  INPUT tokens : {inp_d:+,.0f} ({inp_p:+.2f}%)   <- {flag} lever (tool-def prune)")
print(f"  cost (usd)   : ${cost_d:+.4f} ({cost_p:+.2f}%)")
print()

# Headline reads off the INPUT-token median — the lever the first attempt could
# not isolate. Negative = ON pruned input tokens (the flag's intended effect).
if inp_d < 0:
    print(f"VERDICT (input-token lever): {flag}=ON saved a median "
          f"{abs(inp_d):,.0f} input tokens ({abs(inp_p):.2f}%) per pair.")
elif inp_d > 0:
    print(f"VERDICT (input-token lever): {flag}=ON ADDED a median "
          f"{inp_d:,.0f} input tokens ({inp_p:.2f}%) per pair — no input saving.")
else:
    print(f"VERDICT (input-token lever): {flag}=ON had no median input-token effect.")
print(f"  cost median: {'CHEAPER' if cost_d < 0 else 'COSTLIER' if cost_d > 0 else 'flat'} "
      f"(${cost_d:+.4f}, {cost_p:+.2f}%).")
print("  Graduation decision stays operator-gated (ADR 0184/0185).")
PY
echo
echo "Manual-handoff: NOTHING merged, pushed, or pruned. Worktrees left for review:"
for trial in $(seq 1 "$TRIALS"); do
    for arm in off on; do
        echo "  $REPO_ROOT/../chimera-soak-flag-${SPEC_SLUG}-${arm}-t${trial}-${STAMP}"
    done
done
echo "Discard them yourself with: git worktree prune"
} | tee "$REPORT"

echo
echo "[flag_soak] report written: $REPORT"
exit 0
