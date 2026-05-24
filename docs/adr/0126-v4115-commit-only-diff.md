# ADR 0126 — v4.115 inspects HEAD's own commit diff, not cumulative `base..HEAD`

Date: 2026-05-24
Status: Accepted

## Context

`check_commit_message_diff_drift` (v4.115, ADR 0115) validates that any
rooted path cited in an `[agent]` commit message body actually appears in
the commit's diff. The original implementation compared claims against
`git diff --name-only <base_ref>..<head_ref>` with `base_ref="main"` and
`head_ref="HEAD"` — i.e. the cumulative branch diff.

That semantic is incidentally correct only when the agent has made
exactly one commit on the branch. It breaks the moment `HEAD == base_ref`
or there is no path-overlap between the branch tip's own changes and the
cumulative range.

### The smoking gun: soak v29

Soak v29 spawned a worktree via `git worktree add -b chimera-soak/v29-...
worktree main`. The branch HEAD was identical to main's HEAD: commit
`ccf9510` — the squash-merge of PR #23, prefixed `[agent] v26 follow-up:
...` with a body that mentioned `tests/test_charter_file_count.py`.

Every cycle that ran `check_commit_message_diff_drift` against that
HEAD computed:

- `git log -1 --format=%s HEAD` → `[agent] v26 follow-up: ...` → passes
  the `[agent]`-prefix gate
- `git diff --name-only main..HEAD` → empty (HEAD == main HEAD)
- Extracted path claims from message body → `["tests/test_charter_file_count.py"]`
- Filter (claim ∉ empty set) → drift fires

The trust journal at
`/Users/dave/chimera-soak-v29-2026-05-24-1710/state/trust_state.json`
shows v4.115 firing five consecutive times across cycles 134-136,
demoting trust 5→4→3→2→1→0. Once at T0, v4.117 blocked all further
commits per its contract:

```
PermissionError: git commit blocked: trust state is T0 (cumulative detector
firings have collapsed trust). Operator must promote the agent before further commits.
```

The detector chain worked exactly as designed. v4.115 was just asking
the wrong question.

## Decision

Change v4.115 to inspect the HEAD commit's **own** diff:

```python
touched = subprocess.run(
    ["git", "show", "--name-only", "--format=", head_ref],
    cwd=str(root), capture_output=True, text=True, timeout=15,
)
```

The `--format=` (empty pretty-format) suppresses the commit header; the
output is exactly the list of paths touched by `<head_ref>`. Semantic
intent — "did the agent's commit message reference files that aren't in
THAT commit's diff?" — is now expressed directly.

The `base_ref` parameter is retained on the function signature for
backward compatibility with callers and for tests that need to assert
the new commit-only semantic regardless of the cumulative diff. It is
no longer read by the implementation.

## Consequences

**Positive**

- Fresh-fork soak branches (HEAD == main HEAD) no longer false-fire
  v4.115 every cycle on whatever happened to be on main's tip.
- Multi-commit feature branches where an earlier commit already added a
  cited file but a later `[agent]` commit re-references it without
  re-touching it now fire correctly (the earlier commit's contribution
  is no longer masking honest current-commit drift either way).
- The semantic now matches the docstring's stated intent rather than an
  incidental property of one-commit branches.

**Negative**

- `base_ref` parameter is dead weight on the signature. Kept for
  backward compatibility; can be deprecated separately.
- Detectors that consume v4.115's output (`commit_message_diff_drift`
  finish reason, escalation, remediation, trust delta) are unchanged.
  Anyone who was relying on the cumulative-diff semantics gets stricter
  enforcement on multi-commit branches.

## Tests

`tests/test_commit_message_diff_drift.py` adds:

- `test_commit_only_semantics_when_base_equals_head` — explicit
  `base_ref="HEAD"`; honest [agent] commit citing files in its own
  diff must not fire.
- `test_v29_fresh_fork_does_not_fire` — reconstructs the v29 shape:
  `[agent]` commit lands on main, fresh branch forked off main with
  HEAD == main HEAD; default `base_ref="main"`; must not fire.
- `test_genuine_commit_only_drift_still_fires` — HEAD's own commit
  diff omits a path the message claims → still fires (regression
  preservation for the v20-relaunch shape this detector was built
  for, expressed in commit-only terms).

The existing `test_v20_relaunch_regression_fires` continues to pass
because the unstaged claim is also absent from HEAD's own diff.

## Out of scope

- `check_provenance_claim_valid` (v4.118) — different concern
  (version/ADR tokens, not paths). File separately if a similar bug is
  found.
- Regex / exit code / wire-up of v4.115 — unchanged.
- Deprecating `base_ref` from the signature — separate cleanup.
- Survey of other detectors for cumulative-vs-commit-only bugs — file
  per-detector ADRs if found.
