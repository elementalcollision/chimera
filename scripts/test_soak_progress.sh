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

# ===============================================================
# PR #117 follow-up: phase-1 soft-sentinel (v36-postmortem defect B)
# ===============================================================
#
# soak_phase1_deliverable_landed gives phase 1 (engines OFF, no commits)
# a documented file-presence exit path symmetric with phase 2's
# commit-based mechanism. Cases 10–13 cover:
#   10 — fires when deliverable exists AND contains READY marker
#   11 — does NOT fire when file missing or marker absent
#   12 — backward compat: empty allowed_files returns error (caller
#        gates on the env vars being set, like phase_loop does)
#   13 — phase-2 sentinel preserved (smoke against soak_lib.sh)

TMPDIR_P1="$(mktemp -d -t soak_phase1_test.XXXXXX)"
trap 'rm -rf "$TMPDIR_P1" "$TMPLOG"' EXIT
mkdir -p "$TMPDIR_P1/mind/research"

# ── Case 10: fires when deliverable present + marker present ───
echo "Case 10: phase-1 sentinel fires when deliverable + READY marker present"
cat > "$TMPDIR_P1/mind/research/v36-locomo-temporal-one-item-classification.md" <<'NOTE_EOF'
# v36 classification

Classified conv-26::qa14 as H1.

## READY-FOR-REMEDIATION

R1 — no code change.
NOTE_EOF
soak_phase1_deliverable_landed \
    "$TMPDIR_P1" \
    "mind/research/v36-locomo-temporal-one-item-classification.md" \
    "true"
assert_eq "$?" "0" "sentinel fires on file + marker + test=true"

# ── Case 11: does NOT fire on missing file or missing marker ───
echo "Case 11: phase-1 sentinel does not false-positive"

# 11a: file missing entirely
soak_phase1_deliverable_landed \
    "$TMPDIR_P1" \
    "mind/research/does-not-exist.md" \
    "true"
assert_eq "$?" "1" "sentinel quiet when file missing"

# 11b: file exists but lacks marker
cat > "$TMPDIR_P1/mind/research/v34-no-marker.md" <<'NOTE_EOF'
# in-progress design note

Still drafting. Not ready yet.
NOTE_EOF
soak_phase1_deliverable_landed \
    "$TMPDIR_P1" \
    "mind/research/v34-no-marker.md" \
    "true"
assert_eq "$?" "1" "sentinel quiet when marker absent"

# 11c: test_cmd fails
soak_phase1_deliverable_landed \
    "$TMPDIR_P1" \
    "mind/research/v36-locomo-temporal-one-item-classification.md" \
    "false"
assert_eq "$?" "1" "sentinel quiet when test_cmd fails"

# 11d: custom marker still recognised
cat > "$TMPDIR_P1/mind/research/v34-preference-dialectic-design.md" <<'NOTE_EOF'
# v34 design

## READY-FOR-REMEDIATION

Locked design table follows.
NOTE_EOF
soak_phase1_deliverable_landed \
    "$TMPDIR_P1" \
    "mind/research/v34-preference-dialectic-design.md" \
    "true" \
    "## READY-FOR-REMEDIATION"
assert_eq "$?" "0" "sentinel fires under explicit marker arg (v34 shape)"

# ── Case 12: backward compat — bad args return 2 ───────────────
echo "Case 12: backward compat — bad args return 2 (callers gate on env vars)"
soak_phase1_deliverable_landed "$TMPDIR_P1" "" "true" 2>/dev/null
assert_eq "$?" "2" "empty allowed_files → error 2"
soak_phase1_deliverable_landed "" "x.md" "true" 2>/dev/null
assert_eq "$?" "2" "empty worktree → error 2"
soak_phase1_deliverable_landed "$TMPDIR_P1" "x.md" "" 2>/dev/null
assert_eq "$?" "2" "empty test_cmd → error 2"
# The runner's phase_loop only invokes the sentinel when BOTH
# SOFT_SENTINEL_ALLOWED_FILES and SOFT_SENTINEL_TEST_CMD are non-empty,
# so existing soaks that leave these unset get the unchanged legacy
# behaviour (INVESTIGATION_DOC ready_marker_found path only).

# ── Case 13: phase-2 sentinel mechanism preserved ──────────────
echo "Case 13: phase-2 sentinel still works (soak_lib.sh untouched)"
# shellcheck disable=SC1091
. "$HERE/soak_lib.sh"
# Initialise a tiny git worktree-like dir; soak_phase2_deliverable_landed
# only inspects .git existence + git log + git diff. Use a real git init
# so the smoke covers the real codepath.
PHASE2_REPO="$(mktemp -d -t soak_phase2_test.XXXXXX)"
trap 'rm -rf "$TMPDIR_P1" "$TMPLOG" "$PHASE2_REPO"' EXIT
(
    cd "$PHASE2_REPO" \
        && git init -q -b main \
        && git config user.email t@t && git config user.name t \
        && echo seed > seed.txt && git add seed.txt \
        && git commit -q -m "seed" \
        && git checkout -q -b soak/phase2-smoke \
        && mkdir -p chimera/a2a && echo "x" > chimera/a2a/dialectic.py \
        && git add chimera/a2a/dialectic.py \
        && git commit -q -m "[agent] preference-aware dialectic"
) >/dev/null 2>&1
soak_phase2_deliverable_landed \
    "$PHASE2_REPO" \
    "chimera/a2a/dialectic.py" \
    "true"
assert_eq "$?" "0" "phase-2 sentinel still fires on [agent] commit + scoped diff + test=true"

if [ "$fail" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "FAILURES"
    exit 1
fi
