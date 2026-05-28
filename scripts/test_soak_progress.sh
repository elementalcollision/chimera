#!/usr/bin/env bash
# scripts/test_soak_progress.sh — smoke test for soak_check_forward_progress.
#
# Exercises the watchdog helper added to _soak_common.sh in isolation:
# no DB, no chimera process, just the helper's stall counter against
# synthetic (cycle, spend) sequences. Validates the three behaviours
# the v35-postmortem ladder closure depends on:
#
#   1. Grace period skips the check.
#   2. Stall is detected when both cycle AND spend are unchanged.
#   3. Forward progress (either value changing) resets the stall counter.
#
# Usage: bash scripts/test_soak_progress.sh
# Exits 0 on pass, 1 on any failure.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$HERE/_soak_common.sh"

fail=0
assert_eq() {
    local got="$1" want="$2" label="$3"
    if [ "$got" = "$want" ]; then
        printf '  PASS %s\n' "$label"
    else
        printf '  FAIL %s: got=%s want=%s\n' "$label" "$got" "$want"
        fail=1
    fi
}

# ── Case 1: grace period (default grace=3) ─────────────────────
echo "Case 1: grace period swallows the first 3 iters even when stalled"
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_reset_forward_progress
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 5 0.10; assert_eq "$?" "0" "iter 1 (grace)"
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 5 0.10; assert_eq "$?" "0" "iter 2 (grace)"
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 5 0.10; assert_eq "$?" "0" "iter 3 (grace)"
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 5 0.10; assert_eq "$?" "0" "iter 4 (1st stall, below thresh=2)"
SOAK_NO_PROGRESS_GRACE=3 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 5 0.10; assert_eq "$?" "1" "iter 5 (2nd stall, abort)"

# ── Case 2: cycle advancing resets the counter ─────────────────
echo "Case 2: cycle progress resets the stall counter"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_reset_forward_progress
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 10 1.00; assert_eq "$?" "0" "iter 1"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 10 1.00; assert_eq "$?" "0" "iter 2 (stall 1)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 10 1.00; assert_eq "$?" "0" "iter 3 (stall 2)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 11 1.00; assert_eq "$?" "0" "iter 4 (cycle up — reset)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 11 1.00; assert_eq "$?" "0" "iter 5 (stall 1 again)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 11 1.00; assert_eq "$?" "0" "iter 6 (stall 2)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=3 soak_check_forward_progress 11 1.00; assert_eq "$?" "1" "iter 7 (stall 3, abort)"

# ── Case 3: spend advancing resets the counter ─────────────────
echo "Case 3: spend progress also resets"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_reset_forward_progress
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 7 2.00; assert_eq "$?" "0" "iter 1"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 7 2.00; assert_eq "$?" "0" "iter 2 (stall 1)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 7 2.05; assert_eq "$?" "0" "iter 3 (spend up — reset)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 7 2.05; assert_eq "$?" "0" "iter 4 (stall 1 again)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 7 2.05; assert_eq "$?" "1" "iter 5 (stall 2, abort)"

# ── Case 4: defaults (N=8, grace=3) — 11 stalled iters trips at iter 11 ─
echo "Case 4: defaults trip at iter (grace + threshold) = 11"
unset SOAK_NO_PROGRESS_GRACE SOAK_NO_PROGRESS_THRESHOLD
soak_reset_forward_progress
rc=0
for i in $(seq 1 10); do
    soak_check_forward_progress 42 3.50 || rc=$?
done
assert_eq "$rc" "0" "iters 1..10 (3 grace + 7 stall, below thresh=8)"
soak_check_forward_progress 42 3.50; assert_eq "$?" "1" "iter 11 (8th stall, abort)"

if [ "$fail" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "FAILURES"
    exit 1
fi
