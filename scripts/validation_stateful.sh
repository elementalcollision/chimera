#!/usr/bin/env bash
# scripts/validation_stateful.sh — stateful fault validation.
#
# Faults a CLASS whose behaviour depends on the SEQUENCE of method calls
# (chimera/runstats.py: RunningStats accumulates across .add()). The bug is an
# accumulation error (self._sum = x instead of +=) so .mean() is wrong only after
# multiple adds — a genuinely stateful bug a single-call test would miss. The
# combined test exercises a call sequence; the agent must fix it, fallback OFF.
#
# This deliberately probes a KNOWN limit: the faithfulness differential uses a
# pure single-string input corpus and CANNOT characterize a stateful class, so it
# goes blind here — faithfulness leans on mutation + the critic. The run records
# what each gate actually does on stateful code.
#
# CAMPAIGN_DRYRUN=1 prints the plan. Never auto-pushes/PRs/merges.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
DRYRUN="${CAMPAIGN_DRYRUN:-0}"

MOD="chimera/runstats.py"
TEST="tests/test_runstats.py"
GOAL="fix RunningStats in chimera/runstats.py so ${TEST} passes"
base="validation/stateful-base-${STAMP}"

export PHASE1_CAP_USD="${PHASE1_CAP_USD:-3.00}"
export PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2400}"
export COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-10}"
export CHIMERA_SOAK_AUTOCOMMIT="0"

if [ "$DRYRUN" = "1" ]; then
    echo "=== validation_stateful.sh plan (dryrun) ==="
    echo "  module   = $MOD (stateful class — RunningStats accumulator)"
    echo "  fault    = self._sum = x   (should be: self._sum += x)"
    echo "  test     = $TEST (call sequence: add,add,add -> mean/count)"
    echo "  base     = $base   fallback = OFF"
    echo "  probes   = the pure-corpus differential goes BLIND on a stateful class;"
    echo "             faithfulness leans on mutation + critic (the documented gap)"
    echo "  goal     = $GOAL"
    exit 0
fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fbwt="$REPO/../stateful-base-${STAMP}"

log "── stateful validation — $MOD ──"
git worktree add -b "$base" "$fbwt" HEAD >/dev/null 2>&1
( cd "$fbwt"
  mkdir -p "$(dirname "$MOD")"
  cat > "$MOD" <<'PYMOD'
"""Running accumulator (stateful) — validation target.

RunningStats accumulates a count and sum across add() calls; mean() returns the
running mean. Correctness depends on the SEQUENCE of calls. NOT for main.
"""

from __future__ import annotations


class RunningStats:
    def __init__(self) -> None:
        self._count = 0
        self._sum = 0.0

    def add(self, x: float) -> None:
        """Accumulate one value."""
        self._sum = x          # BUG: should be `self._sum += x` (loses history)
        self._count += 1

    def count(self) -> int:
        return self._count

    def mean(self) -> float:
        if self._count == 0:
            return 0.0
        return self._sum / self._count
PYMOD
  cat > "$TEST" <<'PYTEST'
"""Stateful contract — RunningStats over a sequence of add() calls. NOT for main."""
from chimera.runstats import RunningStats


def test_mean_over_sequence():
    s = RunningStats()
    for v in (2.0, 4.0, 6.0):
        s.add(v)
    assert s.count() == 3
    assert s.mean() == 4.0          # (2+4+6)/3 — fails if add() doesn't accumulate


def test_single_add():
    s = RunningStats()
    s.add(10.0)
    assert s.count() == 1 and s.mean() == 10.0   # passes even with the bug
PYTEST
  git add "$MOD" "$TEST"
  git commit -q -m "test(validation): INJECTED stateful fault (RunningStats accumulation) — NOT for main" )
red="$(cd "$fbwt" && uv run chimera verify --ruff "$MOD" --test "$TEST" 2>&1 | tail -1)"
log "  base gate (expect FAIL): $red"
git worktree remove "$fbwt" --force >/dev/null 2>&1

log "  launching soak (stateful, fallback OFF)…"
TASK_GOAL="$GOAL" TASK_FILES="$MOD" TASK_TEST="$TEST" TASK_BASE="$base" \
    bash scripts/real_task_soak.sh >/dev/null 2>&1 || true

wt="$(ls -dt "$REPO"/../chimera-soak-realtask-* 2>/dev/null | head -1)"
committed="no"; gate="?"; faithful="?"; diff_signal="?"
if [ -n "$wt" ] && [ -d "$wt" ]; then
    sha="$(cd "$wt" && git log --format='%h' "$base"..HEAD 2>/dev/null | head -1)"
    [ -n "$sha" ] && committed="yes ($sha)"
    gate="$(cd "$wt" && uv run chimera verify --ruff "$MOD" --test "$TEST" 2>&1 | tail -1 | grep -oE 'PASS|FAIL' || echo '?')"
    (cd "$wt" && git show "HEAD:$MOD" 2>/dev/null | grep -qF "self._sum += x") && faithful="yes" || faithful="NO"
    # what did the differential report on this stateful class?
    diff_signal="$(cd "$wt" && uv run chimera faithfulness --target "$MOD" --test "$TEST" --base "$base" 2>&1 | grep -ciE 'BEHAVIOUR DELTA' || echo 0)"
fi
log "── result: committed=$committed gate=$gate faithful=$faithful differential_deltas=$diff_signal ──"
log "   (differential_deltas=0 expected: pure-corpus is blind on a stateful class)"
log "   review: cd $wt && git log --oneline $base..HEAD"
exit 0
