#!/usr/bin/env bash
# scripts/test_soak_progress.sh — smoke test for soak_check_forward_progress
# and soak_check_task_completion.
#
# Exercises the two watchdog helpers in _soak_common.sh in isolation:
# no DB, no chimera process, just the helpers' stall counters against
# synthetic (cycle, spend) sequences and synthetic chimera log files.
#
# Cases 1–4 validate the original (cycle, spend) signal from PR #109.
# Cases 5–9 validate the task-completion signal added in ladder #6
# (v35-postmortem attempt #4): grace, threshold, mixed K, default
# preservation, and either-signal-triggers coexistence.
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

# ===============================================================
# Ladder #6 (v35-postmortem attempt #4): task-completion signal
# ===============================================================

TMPLOG="$(mktemp -t soak_progress_test.XXXXXX)"
trap 'rm -f "$TMPLOG"' EXIT

# Append a single ACT-budget-exceeded line matching the PR #110 format
# from chimera/core/loop.py.
log_completed() {
    local k="$1" total="${2:-3}"
    printf 'WARNING ACT phase budget exceeded: cancelled at 240s (completed=%d/%d tasks)\n' \
        "$k" "$total" >> "$TMPLOG"
}

# ── Case 5: zero-completion stall (grace=2, threshold=3) ───────
echo "Case 5: zero-completion stall trips after grace + threshold"
: > "$TMPLOG"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_reset_forward_progress
# Iter 1 (grace): K=0
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 1 (grace, K=0)"
# Iter 2 (grace): K=0
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 2 (grace, K=0)"
# Iter 3: K=0 (stall 1)
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 3 (stall 1)"
# Iter 4: K=0 (stall 2)
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 4 (stall 2)"
# Iter 5: K=0 (stall 3, abort)
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "1" "iter 5 (stall 3, abort)"

# ── Case 6: mixed signal — K=2 in the middle resets ────────────
echo "Case 6: K>0 in the middle resets the counter"
: > "$TMPLOG"
SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_reset_forward_progress
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 1 (K=0, stall 1)"
log_completed 2; k="$(SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 2 (K=2, reset)"
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 3 (K=0, stall 1)"
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=0 SOAK_NO_COMPLETION_THRESHOLD=3 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 4 (K=0, stall 2, below thresh=3)"

# ── Case 7: grace period swallows leading K=0 ──────────────────
echo "Case 7: grace=2 swallows the first 2 K=0 iters"
: > "$TMPLOG"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=99 soak_reset_forward_progress
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=99 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=99 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 1 (grace)"
log_completed 0; k="$(SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=99 soak_extract_tasks_completed_from_log "$TMPLOG")"
SOAK_NO_COMPLETION_GRACE=2 SOAK_NO_COMPLETION_THRESHOLD=99 soak_check_task_completion "$k"; assert_eq "$?" "0" "iter 2 (grace)"
# Counter must be 0 after grace; verify by reading the global.
assert_eq "${_SOAK_NC_STALL_COUNT:-?}" "0" "stall counter still 0 after grace"

# ── Case 8: default behaviour preserved (K>0 / no log lines) ───
echo "Case 8: K>0 every iter never aborts"
: > "$TMPLOG"
unset SOAK_NO_COMPLETION_GRACE SOAK_NO_COMPLETION_THRESHOLD
soak_reset_forward_progress
rc8=0
for i in $(seq 1 20); do
    log_completed 3 3
    k="$(soak_extract_tasks_completed_from_log "$TMPLOG")"
    soak_check_task_completion "$k" || rc8=$?
done
assert_eq "$rc8" "0" "20 iters with K=3 — never aborts"

# ── Case 9: either signal triggers — (cycle, spend) stall ───────
echo "Case 9: existing (cycle, spend) signal still triggers AND task-completion coexists"
: > "$TMPLOG"
unset SOAK_NO_COMPLETION_GRACE SOAK_NO_COMPLETION_THRESHOLD
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_reset_forward_progress
# (cycle, spend) stalled for 3 iters; task-completion log empty (K unknown).
# (cycle, spend) check should fire at iter 3 (2nd stall).
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 99 9.99; assert_eq "$?" "0" "iter 1 cycle/spend"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 99 9.99; assert_eq "$?" "0" "iter 2 cycle/spend (stall 1)"
SOAK_NO_PROGRESS_GRACE=0 SOAK_NO_PROGRESS_THRESHOLD=2 soak_check_forward_progress 99 9.99; assert_eq "$?" "1" "iter 3 cycle/spend (stall 2, abort)"
# And empty log → task-completion returns 0 (no false positive).
k="$(soak_extract_tasks_completed_from_log "$TMPLOG")"
assert_eq "${k:-empty}" "empty" "no log lines → empty K"
soak_check_task_completion "$k"; assert_eq "$?" "0" "task-completion stays quiet on empty log"

if [ "$fail" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "FAILURES"
    exit 1
fi
