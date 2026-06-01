#!/usr/bin/env bash
# scripts/validation_coupled.sh — COUPLED multi-file fault validation.
#
# Unlike validation_multifile.sh (two INDEPENDENT bugs), this is a single logical
# fault spanning two files that must be fixed CONSISTENTLY: chimera/tempc.py's
# c_to_f and chimera/tempf.py's f_to_c are exact inverses, but both carry the same
# wrong constant (+30 instead of +32). A round-trip test (f_to_c(c_to_f(c))==c)
# PASSES on the consistent-but-wrong pair; direct tests (c_to_f(100)==212) FAIL.
# Fixing only ONE file breaks the round-trip — so the agent must understand the
# coupling and change BOTH files to the matching correct constant.
#
# Fallback OFF; multi-file-aware faithfulness + critic check every file. Collects:
# both files committed? gate green? both faithful (both restored to 32)?
#
# CAMPAIGN_DRYRUN=1 prints the plan. Never auto-pushes/PRs/merges.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
DRYRUN="${CAMPAIGN_DRYRUN:-0}"

MOD_A="chimera/tempc.py"; MOD_B="chimera/tempf.py"
TEST="tests/test_tempconv.py"
GOAL="fix c_to_f (chimera/tempc.py) and f_to_c (chimera/tempf.py) so ${TEST} passes — they are exact inverses and must use the SAME correct constant"
base="validation/coupled-base-${STAMP}"

export PHASE1_CAP_USD="${PHASE1_CAP_USD:-3.50}"
export PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2700}"
export COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-10}"
export CHIMERA_SOAK_AUTOCOMMIT="0"

if [ "$DRYRUN" = "1" ]; then
    echo "=== validation_coupled.sh plan (dryrun) ==="
    echo "  files    = $MOD_A + $MOD_B (COUPLED inverse pair)"
    echo "  fault    = both use +30 / -30 (consistent-but-wrong); correct is 32"
    echo "  coupling = round-trip test passes on the wrong pair; direct tests fail;"
    echo "             fixing one file alone breaks the round-trip → must fix BOTH"
    echo "  test     = $TEST   base = $base   fallback = OFF"
    echo "  goal     = $GOAL"
    exit 0
fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fbwt="$REPO/../coupled-base-${STAMP}"

log "── coupled multi-file validation — $MOD_A + $MOD_B ──"
git worktree add -b "$base" "$fbwt" HEAD >/dev/null 2>&1
( cd "$fbwt"
  cat > "$MOD_A" <<'PYA'
"""Celsius→Fahrenheit. Exact inverse of chimera.tempf.f_to_c — they must share
the same conversion constant. NOT for main."""
from __future__ import annotations


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 30   # BUG: constant should be 32 (and match f_to_c)
PYA
  cat > "$MOD_B" <<'PYB'
"""Fahrenheit→Celsius. Exact inverse of chimera.tempc.c_to_f — they must share
the same conversion constant. NOT for main."""
from __future__ import annotations


def f_to_c(f: float) -> float:
    return (f - 30) * 5 / 9   # BUG: constant should be 32 (and match c_to_f)
PYB
  cat > "$TEST" <<'PYT'
"""Coupled contract — c_to_f and f_to_c are exact inverses sharing one constant.
NOT for main."""
from chimera.tempc import c_to_f
from chimera.tempf import f_to_c


def test_direct_conversions():
    assert c_to_f(100) == 212.0
    assert c_to_f(0) == 32.0
    assert f_to_c(212) == 100.0
    assert f_to_c(32) == 0.0


def test_round_trip_inverse():   # passes on a consistent-but-wrong pair
    for c in (0.0, 37.0, 100.0):
        assert abs(f_to_c(c_to_f(c)) - c) < 1e-9
PYT
  git add "$MOD_A" "$MOD_B" "$TEST"
  git commit -q -m "test(validation): INJECTED coupled fault (temp inverse pair, const 30) — NOT for main" )
red="$(cd "$fbwt" && uv run chimera verify --ruff "$MOD_A" --ruff "$MOD_B" --test "$TEST" 2>&1 | tail -1)"
log "  base gate (expect FAIL on direct, pass on round-trip): $red"
git worktree remove "$fbwt" --force >/dev/null 2>&1

log "  launching soak (coupled 2-file, fallback OFF)…"
TASK_GOAL="$GOAL" TASK_FILES="$MOD_A $MOD_B" TASK_TEST="$TEST" TASK_BASE="$base" \
    bash scripts/real_task_soak.sh >/dev/null 2>&1 || true

wt="$(ls -dt "$REPO"/../chimera-soak-realtask-* 2>/dev/null | head -1)"
committed="no"; gate="?"; a_ok="?"; b_ok="?"; touched="-"
if [ -n "$wt" ] && [ -d "$wt" ]; then
    sha="$(cd "$wt" && git log --format='%h' "$base"..HEAD 2>/dev/null | head -1)"
    [ -n "$sha" ] && committed="yes ($sha)"
    touched="$(cd "$wt" && git diff --name-only "$base"..HEAD 2>/dev/null | grep -E 'chimera/' | tr '\n' ' ')"
    gate="$(cd "$wt" && uv run chimera verify --ruff "$MOD_A" --ruff "$MOD_B" --test "$TEST" 2>&1 | tail -1 | grep -oE 'PASS|FAIL' || echo '?')"
    (cd "$wt" && git show "HEAD:$MOD_A" 2>/dev/null | grep -qE -- '\+ ?32') && a_ok="yes" || a_ok="NO"
    (cd "$wt" && git show "HEAD:$MOD_B" 2>/dev/null | grep -qE -- '- ?32') && b_ok="yes" || b_ok="NO"
fi
log "── result: committed=$committed gate=$gate tempc_fixed=$a_ok tempf_fixed=$b_ok ──"
log "   touched: $touched"
log "   review: cd $wt && git log --oneline $base..HEAD"
exit 0
