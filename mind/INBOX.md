# Inbox — Soak v17 phase 2 (remediation, engines on)

Phase 1's design is in
`mind/research/orphan-worktree-check-design.md` under
`## READY-FOR-REMEDIATION`. Implement the new doctor check.

CHARTER (v4.112 charter extraction will pass this to the witness
panel from this task text):

  1. SCOPE: ONE new check function — `_check_orphan_worktrees` —
     in `chimera/core/doctor.py`. Wire it into the existing
     check registry (`run_checks` or equivalent). NO other doctor
     changes.
  2. SEMANTICS: enumerate `.git/worktrees/<name>/HEAD` files; when
     a branch name matches `chimera-soak/v\d+-` AND the
     worktree directory's mtime is older than the configured
     threshold, return `warn` with a `git worktree remove …`
     suggestion in the message.
  3. PATTERN: follow `_check_orphan_wal` exactly. Same signature
     shape (path arg in, `CheckResult` out). Same status vocab
     (`ok`/`warn`/`error`). Same naming convention.
  4. NO new CLI flags. NO refactor of the `CheckResult` dataclass.
     NO renaming of existing check functions. NO changes to the
     doctor handler in `chimera/cli.py`.
  5. NO subprocess calls to the `git` binary. Read
     `.git/worktrees/` directly. Gracefully handle a missing dir.
  6. The check must NEVER raise. On any failure (perm denied,
     malformed metadata, etc.) → return `ok` with a diagnostic
     message, NOT `error`. False positives in this check are
     far worse than false negatives.
  7. The threshold is read from
     `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS` env var, default 24.
     Document the env knob in the check's docstring.

## Phase 2 tasks

- [ ] Re-read the design from phase 1. If you still endorse the
  approach, proceed.

- [ ] Add `_check_orphan_worktrees(repo_root: Path) -> CheckResult`
  to `chimera/core/doctor.py`. Place it alongside
  `_check_orphan_wal` (the structural precedent). Wire it into
  the `run_checks(...)` registry call list.

- [ ] Extend `tests/test_doctor.py` (do NOT create a new test
  file — the project convention is one file per module). At
  minimum:
    * `test_orphan_worktrees_clean_repo_returns_ok` — repo with
      no .git/worktrees/ → status="ok"
    * `test_orphan_worktrees_fresh_soak_returns_ok` — repo with
      a chimera-soak/* worktree whose mtime is fresh (<24h) →
      status="ok"
    * `test_orphan_worktrees_aged_soak_returns_warn` — repo with
      a chimera-soak/* worktree mtime > threshold → status="warn"
      with a `git worktree remove …` substring in the message
    * `test_orphan_worktrees_threshold_env_knob` — set
      CHIMERA_DOCTOR_WORKTREE_AGE_HOURS=1, fixture has 2h-old
      worktree → status="warn"
    * `test_orphan_worktrees_non_soak_branch_ignored` — worktree
      whose branch doesn't match `chimera-soak/v\d+-` → ignored
      regardless of age
    * `test_orphan_worktrees_malformed_metadata_returns_ok` — a
      worktree directory missing HEAD or with garbage → "ok" with
      diagnostic, NOT "error" (charter #6)

- [ ] Commit your changes with `[agent]` prefix and a one-paragraph
  rationale referencing soak v6-v9's surfacing of orphan
  worktrees (operator had to manually run `git worktree remove`
  multiple times during the soak series).

- [ ] Run the targeted test file: `uv run pytest
  tests/test_doctor.py -q` and write the summary line into
  `mind/research/orphan-worktree-check-remediation.md` under
  `## Test results`.

You are on the soak branch; push is scoped-out via a per-worktree
config override. The operator reviews the branch after the run.

If you find yourself wanting to add more doctor checks "while
you're in there", refactor the CheckResult dataclass, add a CLI
flag for the new check, or use `subprocess.run(['git', ...])`:
STOP. Those are out of charter. v4.112 charter anchoring will
extract the CHARTER section above from this very task text and
pass it to the witness panel. Scope-creep diffs will be rejected.
