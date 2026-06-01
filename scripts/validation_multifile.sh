#!/usr/bin/env bash
# scripts/validation_multifile.sh — multi-file fault validation.
#
# One task whose fix spans TWO files: a boundary fault in chimera/numfmt.py AND
# an inverted-comparison fault in chimera/seqstats.py, both caught by a single
# combined contract test. The agent must edit BOTH modules to green the test,
# commit both (scope-clean), with the now-multi-file-aware faithfulness + critic
# verifying EVERY changed file — fallback OFF so the commit is genuinely the
# agent's own. Collects: both files committed? gate green? both faithful?
#
# CAMPAIGN_DRYRUN=1 prints the plan and exits. Never auto-pushes/PRs/merges;
# base branch + worktrees stay local for human review.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
DRYRUN="${CAMPAIGN_DRYRUN:-0}"

MOD_A="chimera/numfmt.py";   A_OK="while value >= 1024 and"; A_BAD="while value > 1024 and"
MOD_B="chimera/seqstats.py"; B_OK="if v > current";          B_BAD="if v < current"
TEST="tests/test_multifile_validation.py"
GOAL="fix human_bytes (chimera/numfmt.py) and running_max (chimera/seqstats.py) so ${TEST} passes"
base="validation/multifile-base-${STAMP}"

export PHASE1_CAP_USD="${PHASE1_CAP_USD:-3.50}"
export PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2700}"
export COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-10}"
export CHIMERA_SOAK_AUTOCOMMIT="0"

if [ "$DRYRUN" = "1" ]; then
    echo "=== validation_multifile.sh plan (dryrun) ==="
    echo "  files    = $MOD_A + $MOD_B (two-file fix)"
    echo "  faults   = numfmt '$A_OK'->'$A_BAD'; seqstats '$B_OK'->'$B_BAD'"
    echo "  test     = $TEST (combined contract)"
    echo "  base     = $base"
    echo "  caps     = phase1 \$$PHASE1_CAP_USD phase2 \$$PHASE2_CAP_USD wall ${MAX_WALL_SECONDS}s"
    echo "  fallback = OFF"
    echo "  goal     = $GOAL"
    exit 0
fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fbwt="$REPO/../multifile-base-${STAMP}"

log "── multi-file validation — $MOD_A + $MOD_B ──"
git worktree add -b "$base" "$fbwt" HEAD >/dev/null 2>&1
( cd "$fbwt"
  MA="$MOD_A" AO="$A_OK" AB="$A_BAD" MB="$MOD_B" BO="$B_OK" BB="$B_BAD" python3 - <<'PY'
import os, pathlib
for mod, old, new in [(os.environ["MA"], os.environ["AO"], os.environ["AB"]),
                      (os.environ["MB"], os.environ["BO"], os.environ["BB"])]:
    p = pathlib.Path(mod); t = p.read_text()
    assert old in t, f"snippet not found in {mod}: {old!r}"
    p.write_text(t.replace(old, new, 1))
PY
  cat > "$TEST" <<'PYTEST'
"""Multi-file validation contract — numfmt.human_bytes + seqstats.running_max.

Operator-authored for the multi-file fault validation; the fix must edit BOTH
chimera/numfmt.py AND chimera/seqstats.py to pass. NOT for main.
"""
from chimera.numfmt import human_bytes
from chimera.seqstats import running_max


def test_human_bytes_boundary():
    assert human_bytes(1024) == "1.0 KiB"
    assert human_bytes(512) == "512 B"


def test_running_max_cumulative():
    assert running_max([3, 1, 4, 1, 5]) == [3, 3, 4, 4, 5]
    assert running_max([1, 2, 2, 1]) == [1, 2, 2, 2]
PYTEST
  git add "$MOD_A" "$MOD_B" "$TEST"
  git commit -q -m "test(validation): INJECTED two-file fault + combined test — NOT for main" )
red="$(cd "$fbwt" && uv run chimera verify --ruff "$MOD_A" --ruff "$MOD_B" --test "$TEST" 2>&1 | tail -1)"
log "  base gate (expect FAIL): $red"
git worktree remove "$fbwt" --force >/dev/null 2>&1

log "  launching soak (TASK_FILES=2, fallback OFF)…"
TASK_GOAL="$GOAL" TASK_FILES="$MOD_A $MOD_B" TASK_TEST="$TEST" TASK_BASE="$base" \
    bash scripts/real_task_soak.sh >/dev/null 2>&1 || true

wt="$(ls -dt "$REPO"/../chimera-soak-realtask-* 2>/dev/null | head -1)"
committed="no"; gate="?"; a_ok="?"; b_ok="?"; touched="-"
if [ -n "$wt" ] && [ -d "$wt" ]; then
    sha="$(cd "$wt" && git log --format='%h' "$base"..HEAD 2>/dev/null | head -1)"
    [ -n "$sha" ] && committed="yes ($sha)"
    touched="$(cd "$wt" && git diff --name-only "$base"..HEAD 2>/dev/null | grep -E 'chimera/' | tr '\n' ' ')"
    gate="$(cd "$wt" && uv run chimera verify --ruff "$MOD_A" --ruff "$MOD_B" --test "$TEST" 2>&1 | tail -1 | grep -oE 'PASS|FAIL' || echo '?')"
    (cd "$wt" && git show "HEAD:$MOD_A" 2>/dev/null | grep -qF "$A_OK") && a_ok="yes" || a_ok="NO"
    (cd "$wt" && git show "HEAD:$MOD_B" 2>/dev/null | grep -qF "$B_OK") && b_ok="yes" || b_ok="NO"
fi
log "── result: committed=$committed gate=$gate numfmt_faithful=$a_ok seqstats_faithful=$b_ok ──"
log "   touched: $touched"
log "   review: cd $wt && git log --oneline $base..HEAD"
exit 0
