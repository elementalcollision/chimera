#!/usr/bin/env bash
# scripts/ab_soak.sh — code-model A/B soak (ADR 0183 Pillar A.1).
#
# Runs the SAME backlog spec through real_task_soak.sh TWICE — once per model
# arm — pinning ACT to each model via CHIMERA_ACT_FORCE_MODEL, then scores the
# two runs head-to-head from their `[soak-outcome]` lines and records both into
# the outcome ledger with arm-tagged run_ids. This is the measurement ADR 0183
# A.1 gates the code-tier default-routing flip on: point ACT's CRAWL routing at
# the `code` tier ONLY if its kimi lead wins on gate-pass (or matches at lower
# cost-per-landed-change) against the incumbent sonnet lead.
#
# The two arms differ ONLY in the model; identical spec, base, gates, caps, and
# INBOX. The `code` and `sonnet` tiers differ only in their LEAD rung, so the
# faithful tier A/B is exactly these two leads on the same task:
#   A (incumbent) = deepseek/deepseek-v4-pro    — sonnet lead == today's CRAWL lead
#   B (code)      = moonshotai/kimi-k2.7-code   — code tier lead (the candidate)
#
# Required env:
#   AB_SPEC      path to the backlog spec to run both arms against
#                (e.g. mind/ab/codetier-probe.md). Its YAML frontmatter supplies
#                TASK_GOAL/TASK_FILES/TASK_TEST/TASK_BASE — same contract as the
#                daily CRAWL picker.
# Optional env:
#   AB_ARM_A_MODEL / AB_ARM_B_MODEL   override the two model ids (must be ladder
#                models or aliases — see `chimera tiers`).
#   AB_LABEL_A   / AB_LABEL_B          short labels for the run_id / report.
#   TASK_DRYRUN=1   resolve + print both arms' configs and exit WITHOUT spend.
#   Any real_task_soak.sh knob (PHASE1_CAP_USD, MAX_WALL_SECONDS, …) passes
#   through to both arms unchanged — set caps once, both arms inherit them.
#
# Manual-handoff: each arm stops with its branch in its own worktree; NOTHING
# is pushed or merged. The probe spec stays red on base (never merged), so the
# A/B is repeatable — re-run it whenever a new code model is ingested.
#
# Exit codes: 0 both arms ran (review the report); 2 usage / spec error.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
REPO_ROOT="$(pwd)"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

: "${AB_SPEC:?AB_SPEC is required (path to the backlog spec both arms run)}"
[ -f "$AB_SPEC" ] || { echo "ab_soak: spec not found: $AB_SPEC" >&2; exit 2; }

ARM_A_MODEL="${AB_ARM_A_MODEL:-deepseek/deepseek-v4-pro}"
ARM_B_MODEL="${AB_ARM_B_MODEL:-moonshotai/kimi-k2.7-code}"
LABEL_A="${AB_LABEL_A:-incumbent}"
LABEL_B="${AB_LABEL_B:-code}"

# Resolve the spec's TASK_* via the same parser the CRAWL picker uses, so a spec
# that works for the daily loop works here verbatim. Fails closed on an invalid
# spec (the parser reports errors instead of raising).
eval "$(uv run python - "$AB_SPEC" <<'PY'
import shlex, sys
from pathlib import Path
from chimera.core.backlog import parse_spec
spec = parse_spec(Path(sys.argv[1]))
if not spec.valid:
    sys.stderr.write("ab_soak: invalid spec: " + "; ".join(spec.errors) + "\n")
    print("AB_SPEC_INVALID=1")
    raise SystemExit(0)
print(f"SPEC_SLUG={shlex.quote(spec.slug)}")
for k, v in spec.task_env().items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
[ "${AB_SPEC_INVALID:-0}" = "1" ] && exit 2

# A caller (e.g. ab_battery.sh) may pin the base to a fixed SHA so a concurrent
# merge can't move the ref mid-run and trip the phase-2 sentinel. This override
# wins over the spec's `base:` frontmatter.
[ -n "${TASK_BASE_OVERRIDE:-}" ] && export TASK_BASE="$TASK_BASE_OVERRIDE"

STATE_DIR="${CHIMERA_STATE_DIR:-$REPO_ROOT/state}"
AB_STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
REPORT="$STATE_DIR/ab_soak_${SPEC_SLUG}_${AB_STAMP}.txt"
mkdir -p "$STATE_DIR"

# Canonical acceptance test (quality control). Each arm writes its OWN gate test
# (Design 2), so the in-loop gate can't compare quality against the EXTERNAL
# spec — a model can pass by under-implementing + under-testing in tandem (the
# 2026-06-15 first-run finding). When an accept test is present, ab_soak runs it
# against each arm's produced module after the soak and scores spec-pass; the
# verdict then prefers correctness, with cost breaking ties at equal quality.
# Default: a sibling `<spec>.accept.py`; override with AB_ACCEPT. Empty → the
# cost-only verdict (clearly labelled UNGRADED).
ACCEPT="${AB_ACCEPT:-${AB_SPEC%.md}.accept.py}"
ACCEPT_ABS=""
[ -f "$ACCEPT" ] && ACCEPT_ABS="$(cd "$(dirname "$ACCEPT")" && pwd)/$(basename "$ACCEPT")"

echo "=== ab_soak: ${SPEC_SLUG} ==="
echo "  goal  : $TASK_GOAL"
echo "  files : $TASK_FILES"
echo "  test  : ${TASK_TEST:-<full suite>}"
echo "  base  : ${TASK_BASE:-main}"
echo "  accept: ${ACCEPT_ABS:-<none — cost-only verdict>}"
echo "  arm A ($LABEL_A): $ARM_A_MODEL"
echo "  arm B ($LABEL_B): $ARM_B_MODEL"
echo "─────────────────────────────────────────────────────────────"

# run_arm LABEL MODEL → echoes the parsed outcome as "gate committed cost branch run_id"
run_arm() {
    local label="$1" model="$2"
    local out; out="$(mktemp -t ab-soak-"$label".XXXXXX)"
    echo "── arm '$label' → CHIMERA_ACT_FORCE_MODEL=$model ──" >&2
    CHIMERA_ACT_FORCE_MODEL="$model" \
    RUN_ID_SUFFIX="ab-${label}" \
    WORKTREE="$REPO_ROOT/../chimera-soak-ab-${SPEC_SLUG}-${label}-${AB_STAMP}" \
        bash "$REPO_ROOT/scripts/real_task_soak.sh" 2>&1 | tee "$out" >&2
    local line; line="$(grep '\[soak-outcome\]' "$out" | tail -1 || true)"
    rm -f "$out"
    if [ -z "$line" ]; then
        echo "fail 0 0 - ab-${label}-noline"
        return
    fi
    # Parse key=val tokens off the stable [soak-outcome] line into O_* vars.
    eval "$(printf '%s\n' "$line" | sed -E 's/.*\[soak-outcome\] //; s/([a-z_]+)=([^ ]*)/O_\1="\2"/g')"
    # shellcheck disable=SC2154  # O_* are assigned by the eval above (sed → O_<key>=<val>)
    local gate="${O_gate:-fail}" committed="${O_committed:-0}" cost="${O_cost_usd:-0}"
    local branch="${O_branch:-}" base="${O_base:-main}" rid="${O_run_id:-ab-${label}}"
    # Record into the ledger (arm-tagged slug + run_id) for accrued evidence.
    uv run chimera crawl record --run-id "$rid" \
        --slug "${SPEC_SLUG}-${label}" --gate "$gate" \
        --committed "$committed" --cost-usd "$cost" \
        --branch "$branch" --base "$base" >&2 2>&1 || true
    echo "$gate $committed $cost $branch $rid"
}

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    echo "(dryrun) arm A config:"; CHIMERA_ACT_FORCE_MODEL="$ARM_A_MODEL" RUN_ID_SUFFIX="ab-${LABEL_A}" TASK_DRYRUN=1 bash "$REPO_ROOT/scripts/real_task_soak.sh" | sed 's/^/  A| /'
    echo "(dryrun) arm B config:"; CHIMERA_ACT_FORCE_MODEL="$ARM_B_MODEL" RUN_ID_SUFFIX="ab-${LABEL_B}" TASK_DRYRUN=1 bash "$REPO_ROOT/scripts/real_task_soak.sh" | sed 's/^/  B| /'
    echo "(dryrun) no soak launched, no spend, no ledger writes."
    exit 0
fi

read -r A_GATE A_COMMITTED A_COST A_BRANCH A_RUNID <<<"$(run_arm "$LABEL_A" "$ARM_A_MODEL")"
read -r B_GATE B_COMMITTED B_COST B_BRANCH B_RUNID <<<"$(run_arm "$LABEL_B" "$ARM_B_MODEL")"

# grade_accept WORKTREE → echoes "passed total" of the canonical acceptance test
# run against that arm's PRODUCED module (held identical across arms). "- -" when
# no accept test is configured; "0 N" when the arm produced nothing importable.
grade_accept() {
    local wt="$1"
    [ -n "$ACCEPT_ABS" ] || { echo "- -"; return; }
    [ -d "$wt" ] || { echo "0 0"; return; }
    cp "$ACCEPT_ABS" "$wt/tests/_ab_accept.py" 2>/dev/null || { echo "0 0"; return; }
    local out; out="$(cd "$wt" && uv run pytest tests/_ab_accept.py -q --no-header -p no:cacheprovider 2>&1)"
    rm -f "$wt/tests/_ab_accept.py" 2>/dev/null || true
    local p f e
    p="$(printf '%s' "$out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' | tail -1)"
    f="$(printf '%s' "$out" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' | tail -1)"
    e="$(printf '%s' "$out" | grep -oE '[0-9]+ error'  | grep -oE '[0-9]+' | tail -1)"
    p="${p:-0}"; f="${f:-0}"; e="${e:-0}"
    echo "$p $((p + f + e))"
}

WT_A="$REPO_ROOT/../chimera-soak-ab-${SPEC_SLUG}-${LABEL_A}-${AB_STAMP}"
WT_B="$REPO_ROOT/../chimera-soak-ab-${SPEC_SLUG}-${LABEL_B}-${AB_STAMP}"
read -r A_ACC A_ACCTOT <<<"$(grade_accept "$WT_A")"
read -r B_ACC B_ACCTOT <<<"$(grade_accept "$WT_B")"

# ── verdict ────────────────────────────────────────────────────
# A landed change = gate pass AND ≥1 [agent] commit. With an acceptance test,
# QUALITY (spec-pass) is the primary axis — cost only breaks a quality tie, so a
# cheaper arm can't win by doing less (ADR 0183 A.1; 2026-06-15 finding). Without
# one, fall back to the cost-only verdict, clearly labelled UNGRADED.
landed() { [ "$1" = "pass" ] && [ "${2:-0}" -ge 1 ]; }
cheaper() {  # → "A"|"B"|"TIE"
    if awk -v a="$A_COST" -v b="$B_COST" 'BEGIN{exit !(b < a)}'; then echo B
    elif awk -v a="$A_COST" -v b="$B_COST" 'BEGIN{exit !(a < b)}'; then echo A
    else echo TIE; fi
}
VERDICT=""
if [ -n "$ACCEPT_ABS" ]; then
    A_OK=0; B_OK=0
    landed "$A_GATE" "$A_COMMITTED" && A_OK=1
    landed "$B_GATE" "$B_COMMITTED" && B_OK=1
    if [ "$A_OK" = 0 ] && [ "$B_OK" = 0 ]; then
        VERDICT="INCONCLUSIVE — neither arm landed a gated commit"
    elif [ "$A_ACC" -gt "$B_ACC" ]; then
        VERDICT="A ($LABEL_A / $ARM_A_MODEL) — higher spec-pass ($A_ACC/$A_ACCTOT vs $B_ACC/$B_ACCTOT)"
    elif [ "$B_ACC" -gt "$A_ACC" ]; then
        VERDICT="B ($LABEL_B / $ARM_B_MODEL) — higher spec-pass ($B_ACC/$B_ACCTOT vs $A_ACC/$A_ACCTOT)"
    else
        case "$(cheaper)" in
            A) VERDICT="A ($LABEL_A / $ARM_A_MODEL) — equal spec-pass ($A_ACC/$A_ACCTOT), A cheaper (\$$A_COST < \$$B_COST)";;
            B) VERDICT="B ($LABEL_B / $ARM_B_MODEL) — equal spec-pass ($B_ACC/$B_ACCTOT), B cheaper (\$$B_COST < \$$A_COST)";;
            *) VERDICT="TIE — equal spec-pass ($A_ACC/$A_ACCTOT) at equal cost (\$$A_COST)";;
        esac
    fi
else
    # UNGRADED fallback: cost-only (gameable — see the 2026-06-15 finding).
    if landed "$A_GATE" "$A_COMMITTED" && landed "$B_GATE" "$B_COMMITTED"; then
        case "$(cheaper)" in
            B) VERDICT="(UNGRADED) B ($LABEL_B / $ARM_B_MODEL) — both landed, B cheaper (\$$B_COST < \$$A_COST)";;
            A) VERDICT="(UNGRADED) A ($LABEL_A / $ARM_A_MODEL) — both landed, A cheaper (\$$A_COST < \$$B_COST)";;
            *) VERDICT="(UNGRADED) TIE — both landed at equal cost (\$$A_COST)";;
        esac
    elif landed "$A_GATE" "$A_COMMITTED"; then
        VERDICT="(UNGRADED) A ($LABEL_A / $ARM_A_MODEL) — only A landed"
    elif landed "$B_GATE" "$B_COMMITTED"; then
        VERDICT="(UNGRADED) B ($LABEL_B / $ARM_B_MODEL) — only B landed"
    else
        VERDICT="INCONCLUSIVE — neither arm landed a gated commit"
    fi
fi

{
echo "=== ab_soak report: ${SPEC_SLUG} (${AB_STAMP}) ==="
echo "spec: $AB_SPEC"
echo "goal: $TASK_GOAL"
echo "accept: ${ACCEPT_ABS:-<none — cost-only, UNGRADED>}"
echo
printf '%-12s %-28s %-6s %-9s %-10s %-10s %s\n' "arm" "model" "gate" "committed" "cost_usd" "spec_pass" "branch"
printf '%-12s %-28s %-6s %-9s %-10s %-10s %s\n' "$LABEL_A" "$ARM_A_MODEL" "$A_GATE" "$A_COMMITTED" "$A_COST" "$A_ACC/$A_ACCTOT" "$A_BRANCH"
printf '%-12s %-28s %-6s %-9s %-10s %-10s %s\n' "$LABEL_B" "$ARM_B_MODEL" "$B_GATE" "$B_COMMITTED" "$B_COST" "$B_ACC/$B_ACCTOT" "$B_BRANCH"
echo
echo "VERDICT: $VERDICT"
echo
echo "Ledger run_ids: A=$A_RUNID  B=$B_RUNID"
echo "Review the diffs:  git -C ../chimera-soak-ab-${SPEC_SLUG}-${LABEL_A}-${AB_STAMP} log -p ${TASK_BASE:-main}..$A_BRANCH"
echo "                   git -C ../chimera-soak-ab-${SPEC_SLUG}-${LABEL_B}-${AB_STAMP} log -p ${TASK_BASE:-main}..$B_BRANCH"
echo "Nothing merged (manual-handoff). Discard worktrees with: git worktree prune"
} | tee "$REPORT"

echo
echo "[ab_soak] report written: $REPORT"
exit 0
