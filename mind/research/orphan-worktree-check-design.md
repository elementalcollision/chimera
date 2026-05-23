# Orphan Worktree Check — Design

## Motivation

Soak v6–v9 surfaced a gap: `chimera doctor` catches orphan WAL files
(`_check_orphan_wal`) but has no symmetric check for orphan git
worktrees left behind by killed soak runners. Operators only notice
via `git worktree list`, which requires the git binary.

## Worktree Listing — Approach (b)

Read `.git/worktrees/` directory directly. This is preferred over
`git worktree list --porcelain` because:

- **No git dependency** — works when the git binary is missing
- **Deterministic** — pure file enumeration; no subprocess overhead
- **Graceful** — missing directory simply means no linked worktrees

### Directory layout

```
.git/worktrees/<name>/
    gitdir       # file containing the absolute path to this worktree
    HEAD         # file containing the branch ref, e.g. "ref: refs/heads/chimera-soak/v12-..."
    commondir    # (optional, not needed for this check)
    locked       # (optional, not needed for this check)
```

Each subdirectory under `.git/worktrees/` is one linked worktree.
The branch name is read from the `HEAD` file inside it.

### Enumeration logic

```python
def _list_worktrees(repo_root: Path) -> list[tuple[str, Path]]:
    """Return [(name, worktree_path), ...] from .git/worktrees.

    Never raises. Returns empty list on any error (missing dir,
    permission denied, malformed gitdir files).
    """
    wt_dir = repo_root / ".git" / "worktrees"
    if not wt_dir.is_dir():
        return []
    out = []
    for entry in sorted(wt_dir.iterdir()):
        if not entry.is_dir():
            continue
        gitdir_file = entry / "gitdir"
        if not gitdir_file.is_file():
            continue
        try:
            wt_path = Path(gitdir_file.read_text().strip())
        except OSError:
            continue
        out.append((entry.name, wt_path))
    return out
```

### Soak-branch detection

A worktree is considered a "soak fixture" when its HEAD branch
matches the pattern:

```python
re.match(r"^chimera-soak/v\d+-", branch)
```

The branch name is extracted from `.git/worktrees/<name>/HEAD`:

```python
def _worktree_branch(repo_root: Path, name: str) -> str | None:
    head_file = repo_root / ".git" / "worktrees" / name / "HEAD"
    if not head_file.is_file():
        return None
    try:
        raw = head_file.read_text().strip()
    except OSError:
        return None
    # HEAD contains e.g. "ref: refs/heads/chimera-soak/v12-fix-graph"
    ref_prefix = "ref: refs/heads/"
    if raw.startswith(ref_prefix):
        return raw[len(ref_prefix):]
    # Detached HEAD would be a commit hash — not our concern for soak
    # detection; return None.
    return None
```

### Age check

The worktree's age is determined by `mtime` of the `.git/worktrees/<name>/`
directory (or the `gitdir` file inside it). The `_check_orphan_worktrees`
function gets its threshold from `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS`
(default 24). A worktree whose mtime is older than the threshold AND
whose branch matches the soak pattern is flagged as orphaned.

## Structural Precedent: `_check_orphan_wal`

The closest existing check is `_check_orphan_wal(state_dir: Path) -> CheckResult`
in `chimera/core/doctor.py`. Key patterns to mirror:

1. **Signature shape**: takes a path argument, returns `CheckResult`.
2. **Status vocabulary**: `ok` / `warn` / `error`.
3. **Never raises**: on any error, return `ok` with diagnostic message.
4. **Threshold from env**: WAL uses a hardcoded `_ORPHAN_WAL_THRESHOLD`;
   the new check uses an env var instead.
5. **Actionable message**: the WAL check suggests a concrete fix command;
   the worktree check will suggest `git worktree remove <path>`.

## Check Registry

`run_checks()` in `chimera/core/doctor.py` collects all results. The new
check will be added there. It needs `repo_root` — which other checks
don't currently need. Options:

- Accept `repo_root: Path` as a parameter to `_check_orphan_worktrees`,
  then call it from `run_checks()` with `Path.cwd()` (the convention
  is that the agent always runs from the repo root).
- Or derive `repo_root` internally via `Path.cwd()`.

Prefer the explicit parameter: mirror the shape of other checks
(receive their input; don't reach for globals). But `run_checks()`
currently takes no arguments for paths. However, `_check_orphan_wal`
reads `state_dir` from the parameter; `run_checks()` resolves
`CHIMERA_STATE_DIR` before calling it. Similarly, `run_checks()` can
resolve the repo root with `Path.cwd()` and pass it.

**Decision**: `_check_orphan_worktrees(repo_root: Path) -> CheckResult`.
`run_checks()` passes `repo_root=Path.cwd()`.

### Suggested placement in run_checks()

After `_check_concurrent_soak_runners` (the other soak-related check),
before `*_check_provider_keys()`.

## READY-FOR-REMEDIATION

(a) Function signature:
    `def _check_orphan_worktrees(repo_root: Path) -> CheckResult:`

(b) Soak-branch pattern:
    `re.match(r"^chimera-soak/v\d+-", branch)` — where `branch` is
    extracted from `.git/worktrees/<name>/HEAD` (stripping the
    `ref: refs/heads/` prefix).

(c) Age threshold env knob:
    `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS`, default `24`. Read via
    `int(os.environ.get("CHIMERA_DOCTOR_WORKTREE_AGE_HOURS", "24"))`.

(d) Pseudocode tests:

```python
def test_orphan_worktrees_ok_fresh_worktree(repo_root: Path):
    # Given: a worktree directory under .git/worktrees/fresh-soak/
    #   with a HEAD file pointing at "chimera-soak/v12-foo"
    #   whose gitdir file mtime is < 1 minute ago
    # When: _check_orphan_worktrees(repo_root) is called
    # Then: status == "ok" (fresh worktree, below threshold)

def test_orphan_worktrees_warn_aged_soak_worktree(repo_root: Path):
    # Given: a worktree directory under .git/worktrees/stale-soak/
    #   with a HEAD file pointing at "chimera-soak/v9-bar"
    #   whose gitdir file mtime is artificially set to 48 hours ago
    #   CHIMERA_DOCTOR_WORKTREE_AGE_HOURS = 24
    # When: _check_orphan_worktrees(repo_root) is called
    # Then: status == "warn", message contains "git worktree remove"

def test_orphan_worktrees_ok_missing_worktrees_dir(repo_root: Path):
    # Given: .git/worktrees/ does not exist
    # When: _check_orphan_worktrees(repo_root) is called
    # Then: status == "ok", no crash

def test_orphan_worktrees_ok_non_soak_branch(repo_root: Path):
    # Given: a worktree with HEAD pointing at "main"
    # When: _check_orphan_worktrees(repo_root) is called
    # Then: status == "ok" (branch doesn't match soak pattern)
