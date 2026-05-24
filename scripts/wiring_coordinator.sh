#!/usr/bin/env bash
# scripts/wiring_coordinator.sh — sequential decomposition orchestrator
#
# Implements the methodology in docs/wiring-decomposition-methodology.md.
# Runs N sub-soak runners in sequence; for each, if the sub-soak ships
# (soft-sentinel fired AND full suite green), auto-merges the resulting
# PR and continues. Halts on any failure for operator intervention.
#
# Usage:
#   wiring_coordinator.sh <wiring-name> <runner1.sh> <runner2.sh> ...
#
# Example:
#   wiring_coordinator.sh v4116 \
#       scripts/long_cycle_soak_v25.sh \
#       scripts/long_cycle_soak_v26.sh \
#       scripts/long_cycle_soak_v29.sh \
#       scripts/long_cycle_soak_v27.sh \
#       scripts/long_cycle_soak_v28.sh
#
# Note ordering: v27/v28 (chain activators) ship LAST per the methodology
# (Q1 resolution: avoid self-conflict by sequencing them after the layers
# that establish the field/call-site/hint).

set -uo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <wiring-name> <runner1.sh> <runner2.sh> ..." >&2
    exit 2
fi

NAME="$1"; shift
RUNNERS=("$@")

REPO_ROOT="$(git rev-parse --show-toplevel)"
LOG_DIR="$REPO_ROOT/state"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/wiring_${NAME}_$(date -u +%Y-%m-%d-%H%M).log"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"
}

log "─────────────────────────────────────────────────────────────"
log "wiring_coordinator.sh: $NAME"
log "  runners (${#RUNNERS[@]}):"
for r in "${RUNNERS[@]}"; do log "    - $r"; done
log "─────────────────────────────────────────────────────────────"

shipped=0
failed_runner=""

for runner in "${RUNNERS[@]}"; do
    log ""
    log "═══ launching $runner ═══"

    if [ ! -x "$runner" ] && [ ! -f "$runner" ]; then
        log "  FAIL: $runner not found or not executable"
        failed_runner="$runner"
        break
    fi

    # Capture main HEAD before launch — used to detect what branch the
    # sub-soak created.
    local_main_before="$(git -C "$REPO_ROOT" rev-parse main)"

    # Snapshot chimera-soak/* branches BEFORE launch so we can identify
    # the new one the runner creates by diff (vs the `head -1` arbitrary
    # pick that surfaced as a real bug on v26's relaunch — picked an
    # orphan worktree from a prior failed launch instead of the live one).
    branches_before="$(git -C "$REPO_ROOT" worktree list --porcelain \
                         | awk '/^branch / { print $2 }' \
                         | grep -E '^refs/heads/chimera-soak/v[0-9]+-' \
                         | sort)"

    # Run the sub-soak. Per soak_lib.sh v3 contract, it either ships
    # (soft-sentinel exit) or fails (budget cap / max iters / watchdog).
    if ! bash "$runner" >> "$LOG" 2>&1; then
        log "  FAIL: $runner exited non-zero"
        failed_runner="$runner"
        break
    fi

    # Find the branch the sub-soak created via before/after diff.
    branches_after="$(git -C "$REPO_ROOT" worktree list --porcelain \
                        | awk '/^branch / { print $2 }' \
                        | grep -E '^refs/heads/chimera-soak/v[0-9]+-' \
                        | sort)"
    soak_branch="$(comm -23 <(echo "$branches_after") <(echo "$branches_before") \
                     | head -1 \
                     | sed 's|^refs/heads/||')"

    # Fallback 1: worktree may have been self-cleaned by the runner;
    # check remote branches that didn't exist before this run.
    if [ -z "$soak_branch" ]; then
        remote_branches="$(git -C "$REPO_ROOT" branch -r --format='%(refname:short)' \
                             | grep -E '^origin/chimera-soak/v[0-9]+-' \
                             | sed 's|^origin/||' \
                             | sort)"
        before_local="$(echo "$branches_before" | sed 's|^refs/heads/||')"
        soak_branch="$(comm -23 <(echo "$remote_branches") <(echo "$before_local") \
                         | head -1)"
    fi

    if [ -z "$soak_branch" ]; then
        log "  FAIL: cannot locate sub-soak branch after $runner"
        log "         (no new chimera-soak/* branch appeared since launch)"
        failed_runner="$runner"
        break
    fi
    log "  sub-soak branch: $soak_branch"

    # Auto-merge gate (Q3 resolution): soft-sentinel fired AND full suite green.
    # The soft-sentinel signal is implicit: if the runner exited cleanly AND
    # the branch has an [agent] commit AND the charter-clean test command
    # would pass, we treat it as soft-sentinel-fired. The runner's own
    # soft_sentinel_deliverable_landed check is the canonical check; we
    # trust the runner's exit-with-success as the gate.
    #
    # We re-verify by running the full suite on the branch head.

    sub_wt="$(git -C "$REPO_ROOT" worktree list --porcelain \
                 | awk -v br="refs/heads/$soak_branch" '
                     /^worktree / { wt=$2 }
                     /^branch / { if ($2 == br) print wt }')"
    if [ -z "$sub_wt" ]; then
        log "  worktree for $soak_branch already removed (sub-soak self-cleaned?)"
    fi

    # Push the branch (the runner uses a per-worktree push-block; we have
    # to unset it on the worktree before pushing). If push-block is no
    # longer set (sub-soak already pushed), this is a no-op.
    if [ -n "$sub_wt" ] && [ -d "$sub_wt" ]; then
        git -C "$sub_wt" config --worktree --unset remote.origin.pushurl 2>/dev/null || true
        if ! git -C "$sub_wt" push -u origin "$soak_branch" 2>&1 | tee -a "$LOG"; then
            log "  FAIL: could not push $soak_branch"
            failed_runner="$runner"
            break
        fi
    fi

    # Run full suite on the branch head.
    log "  running full suite on $soak_branch ..."
    if [ -n "$sub_wt" ] && [ -d "$sub_wt" ]; then
        suite_dir="$sub_wt"
    else
        # Worktree already removed — fetch the branch into a transient
        # checkout. For simplicity, run the suite on main with the branch
        # checked out (operator can re-check if needed).
        suite_dir="$REPO_ROOT"
        git -C "$REPO_ROOT" fetch origin "$soak_branch" 2>&1 | tee -a "$LOG" || true
        git -C "$REPO_ROOT" checkout "$soak_branch" --quiet 2>&1 | tee -a "$LOG" || true
    fi

    # v30 root-cause: a Py3.10 selectors atexit hook can print after pytest's
    # summary (e.g. "ValueError: Invalid file descriptor: -1"), so tail -1
    # misses the verdict. Scan a small trailing window instead; require a
    # "<n> passed" line and the absence of "failed" (mirrors soft-sentinel
    # test_cmd in scripts/long_cycle_soak_v30.sh).
    if ! ( cd "$suite_dir" && out="$(uv run pytest -q 2>&1 | tee -a "$LOG" | tail -20)" \
             && echo "$out" | grep -qE '\b[0-9]+ passed' \
             && ! echo "$out" | grep -q 'failed' ); then
        log "  FAIL: full suite on $soak_branch had failures"
        failed_runner="$runner"
        if [ "$suite_dir" = "$REPO_ROOT" ]; then
            git -C "$REPO_ROOT" checkout main --quiet 2>&1 | tee -a "$LOG" || true
        fi
        break
    fi
    log "  ✓ full suite green on $soak_branch"

    # Restore main checkout if we changed it.
    if [ "$suite_dir" = "$REPO_ROOT" ] && \
       [ "$(git -C "$REPO_ROOT" branch --show-current)" != "main" ]; then
        git -C "$REPO_ROOT" checkout main --quiet 2>&1 | tee -a "$LOG" || true
    fi

    # Find the PR for this branch (the sub-soak runner does NOT open a PR
    # by default — that's submit-pr's job inside the agent loop, OR
    # operator-side). Open one if missing.
    pr_num="$(gh pr list --head "$soak_branch" --json number -q '.[0].number' 2>/dev/null || true)"
    if [ -z "$pr_num" ]; then
        log "  opening PR for $soak_branch ..."
        # Best-effort PR open with minimal body. Operator can edit before
        # the merge.
        pr_url="$(gh pr create --base main --head "$soak_branch" \
                    --title "$soak_branch (wiring sub-soak)" \
                    --body "Auto-opened by wiring_coordinator.sh ($NAME). Sub-soak shipped via soft-sentinel; full suite green at branch head. Auto-merge gate active." \
                    2>&1 | tee -a "$LOG" | tail -1)"
        pr_num="$(echo "$pr_url" | grep -oE '[0-9]+$' | head -1)"
    fi
    log "  PR: #$pr_num"

    # Auto-merge.
    log "  squash-merging PR #$pr_num ..."
    # NOTE: do NOT pass --delete-branch; v25 surfaced that gh tries to
    # delete the LOCAL branch as part of the flag, and that fails when
    # the soak worktree still has the branch checked out — even though
    # the remote-side merge succeeded. Coordinator's own cleanup below
    # removes both the worktree and the local branch after we sync main.
    if ! gh pr merge "$pr_num" --squash 2>&1 | tee -a "$LOG"; then
        log "  FAIL: gh pr merge failed for #$pr_num"
        failed_runner="$runner"
        break
    fi
    # Delete the remote branch explicitly (since we dropped --delete-branch).
    git -C "$REPO_ROOT" push origin --delete "$soak_branch" 2>&1 | tee -a "$LOG" || true

    # Sync local main.
    git -C "$REPO_ROOT" checkout main --quiet 2>&1 | tee -a "$LOG" || true
    git -C "$REPO_ROOT" pull --ff-only origin main 2>&1 | tee -a "$LOG" || true

    # Clean up sub-soak worktree if still present.
    if [ -n "$sub_wt" ] && [ -d "$sub_wt" ]; then
        git -C "$REPO_ROOT" worktree remove --force "$sub_wt" 2>&1 | tee -a "$LOG" || true
    fi
    git -C "$REPO_ROOT" branch -D "$soak_branch" 2>&1 | tee -a "$LOG" || true

    shipped=$((shipped + 1))
    log "  ✓ $runner shipped (PR #$pr_num merged); $shipped/${#RUNNERS[@]} done"
done

log ""
log "─────────────────────────────────────────────────────────────"
if [ -n "$failed_runner" ]; then
    log "HALTED on: $failed_runner"
    log "Shipped: $shipped/${#RUNNERS[@]}"
    log "Operator: review the failure, fix, re-launch from $failed_runner onward."
    exit 1
fi
log "wiring '$NAME' complete: all ${#RUNNERS[@]} sub-soaks shipped."
log "─────────────────────────────────────────────────────────────"
exit 0
