#!/usr/bin/env bash
# scripts/validation_campaign.sh — deep validation campaign (n=3).
#
# Proves out the no-contract autonomy stack end-to-end across N independent
# fault-injection runs. Each run: inject a real fault into a Chimera-authored
# module (test goes red) on a dedicated base branch, then drive real_task_soak.sh
# with the harness fallback OFF (CHIMERA_SOAK_AUTOCOMMIT=0) so the ONLY path to a
# commit is the agent's own git_commit — with the faithfulness + critic steps
# active in the INBOX. Collect per run: did a genuine [agent] commit land? is the
# gate green? is the fix FAITHFUL (the committed diff vs the known-correct line)?
# Aggregate into a report.
#
# Manifest is fixed (the n=3 design); env knobs tune caps. CAMPAIGN_DRYRUN=1
# prints the plan and exits without running or mutating anything.
#
# Standing rule: this LAUNCHES soaks (a real, costly, long operation) — it is an
# explicit operator action. It never auto-pushes/PRs/merges; branches stay local
# for human review.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"

STAMP="$(date -u +%Y-%m-%d-%H%M)"
REPORT="$REPO/mind/research/validation-campaign-${STAMP}.md"
DRYRUN="${CAMPAIGN_DRYRUN:-0}"

# Per-run caps — "meaningful length": enough to iterate, bounded for cost/time.
export PHASE1_CAP_USD="${PHASE1_CAP_USD:-3.00}"
export PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2400}"
export COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-10}"
export CHIMERA_SOAK_AUTOCOMMIT="0"     # fallback OFF — genuine self-commit only

# Manifest: id | module | test | correct_snippet | buggy_snippet | goal | kind
# (the fault replaces correct_snippet -> buggy_snippet so the test goes red;
#  the agent must restore correct behaviour. correct_snippet is the faithful line.)
RUNS=(
  "v1|chimera/numfmt.py|tests/test_numfmt.py|while value >= 1024 and|while value > 1024 and|fix human_bytes in chimera/numfmt.py so tests/test_numfmt.py passes|faithful-fix"
  "v2|chimera/seqstats.py|tests/test_seqstats.py|current = values[0]|current = 0|fix running_max in chimera/seqstats.py so tests/test_seqstats.py passes|faithful-fix"
  "v3|chimera/strcase.py|tests/test_strcase.py|s[i - 1].islower() or|s[i - 1].isupper() or|fix to_snake in chimera/strcase.py so tests/test_strcase.py passes|regression-tempting"
)

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

if [ "$DRYRUN" = "1" ]; then
    echo "=== validation_campaign.sh plan (dryrun) ==="
    echo "  report   = mind/research/validation-campaign-${STAMP}.md"
    echo "  caps     = phase1 \$$PHASE1_CAP_USD  phase2 \$$PHASE2_CAP_USD  wall ${MAX_WALL_SECONDS}s"
    echo "  fallback = OFF (genuine self-commit only)"
    echo "  runs     = ${#RUNS[@]}"
    for spec in "${RUNS[@]}"; do
        IFS='|' read -r id mod test cold cnew goal kind <<< "$spec"
        echo "  - $id [$kind] $mod (correct: '$cold' -> buggy: '$cnew')"
        echo "      goal: $goal"
    done
    exit 0
fi

mkdir -p "$REPO/mind/research"
{
    echo "# Deep validation campaign — ${STAMP}"
    echo
    echo "n=${#RUNS[@]} fault-injection runs, fallback OFF (genuine self-commit),"
    echo "faithfulness + critic active. Per-run caps: phase1 \$$PHASE1_CAP_USD,"
    echo "phase2 \$$PHASE2_CAP_USD, wall ${MAX_WALL_SECONDS}s."
    echo
    echo "| run | kind | committed | gate | faithful | branch |"
    echo "|---|---|---|---|---|---|"
} > "$REPORT"
log "campaign report: $REPORT"

for spec in "${RUNS[@]}"; do
    IFS='|' read -r id mod test cold cnew goal kind <<< "$spec"
    base="validation/${id}-base-${STAMP}"
    fbwt="$REPO/../campaign-${id}-base-${STAMP}"
    log "── $id [$kind] — $mod ──"

    # Inject the fault on a dedicated base branch via a temp worktree — never
    # touches the main repo's working tree or current branch.
    git worktree add -b "$base" "$fbwt" HEAD >/dev/null 2>&1
    ( cd "$fbwt" && CMOD="$mod" COLD="$cold" CNEW="$cnew" python3 - <<'PY'
import os, pathlib
p = pathlib.Path(os.environ["CMOD"]); t = p.read_text()
old, new = os.environ["COLD"], os.environ["CNEW"]
assert old in t, f"correct snippet not found: {old!r}"
p.write_text(t.replace(old, new, 1))
PY
      git add "$mod"
      git commit -q -m "test(validation): INJECTED FAULT for campaign $id — NOT for main" )
    red="$(cd "$fbwt" && uv run chimera verify --ruff "$mod" --test "$test" 2>&1 | tail -1)"
    log "  base gate (expect FAIL): $red"
    git worktree remove "$fbwt" --force >/dev/null 2>&1

    log "  launching soak (base=$base, fallback OFF)…"
    TASK_GOAL="$goal" TASK_FILES="$mod" TASK_TEST="$test" TASK_BASE="$base" \
        bash scripts/real_task_soak.sh >/dev/null 2>&1 || true

    # collect from the most-recent realtask worktree
    wt="$(ls -dt "$REPO"/../chimera-soak-realtask-* 2>/dev/null | head -1)"
    committed="no"; gate="?"; faithful="?"; sha="-"
    if [ -n "$wt" ] && [ -d "$wt" ]; then
        sha="$(cd "$wt" && git log --format='%h' "$base"..HEAD 2>/dev/null | head -1)"
        [ -n "$sha" ] && committed="yes ($sha)"
        gate="$(cd "$wt" && uv run chimera verify --ruff "$mod" --test "$test" 2>&1 | tail -1 | grep -oE 'PASS|FAIL' || echo '?')"
        # faithful = the committed file contains the correct snippet (behaviour restored)
        if [ -n "$sha" ] && (cd "$wt" && git show "HEAD:$mod" 2>/dev/null | grep -qF "$cold"); then
            faithful="yes"
        elif [ -n "$sha" ]; then
            faithful="NO (correct line absent)"
        fi
    fi
    log "  result: committed=$committed gate=$gate faithful=$faithful"
    echo "| $id | $kind | $committed | $gate | $faithful | $base |" >> "$REPORT"
done

{
    echo
    echo "## Notes"
    echo "- \`committed\` = a genuine \`[agent]\` commit landed with fallback OFF."
    echo "- \`faithful\` = the committed module restored the known-correct line"
    echo "  (for v3, keeping it means NOT dropping the isdigit clause)."
    echo "- Worktrees + base branches left in place for human review; nothing pushed."
} >> "$REPORT"
log "── campaign complete — see $REPORT ──"
cat "$REPORT"
exit 0
