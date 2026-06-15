# Inbox — real-task soak phase 2 (commit-only, engines on)

Phase 1 made the change and `chimera verify` passes. Your ONE job now: COMMIT it.

## Phase 2 — call git_commit FIRST (this is your very first action)
- [ ] Call the **`git_commit` tool** immediately: `git_commit` with
  message="Add a count_by_status(mind_dir) helper to chimera.core.backlog" and paths=[chimera/core/backlog.py tests/test_backlog_status_counts.py]. This SINGLE tool call stages
  AND commits AND returns the new HEAD — it IS the entire commit. The `[agent]`
  prefix is added for you.
  - Do NOT run `git add` yourself, and do NOT stop after staging: raw staging
    WITHOUT a following commit leaves the change uncommitted and the run FAILS
    (this is the #1 way this phase fails — staged but never committed).
  - You do NOT need to run `chimera review` or re-run `chimera verify` first.
    The in-loop critic gate adjudicates faithfulness AUTOMATICALLY as part of the
    `git_commit` call — committing IS how the change gets reviewed.
- [ ] ONLY if `git_commit` returns that the gate REJECTED: read the concern, fix
  it in SCOPE (chimera/core/backlog.py tests/test_backlog_status_counts.py), then call `git_commit` again until HEAD advances.

Manual-handoff: after the commit the runner stops with the branch in the
worktree — NO auto-push/PR/merge.
