# Orphan Worktree Check -- `doctor` Addition

## Context

Soak cycles create linked git worktrees via `scripts/long_cycle_soak*.sh`
on branches matching `chimera-soak/v<N>-*`. When a soak run crashes or is
SIGKILL'd, its worktree directory is left on disk -- an orphan. Over time
orphans accumulate, consuming disk space and confusing operators who run
`git worktree list` or `chimera doctor`.

The existing doctor suite (`chimera/core/doctor.py`) already checks for
orphan WAL files, trust-state observer mode, and concurrent soak runners.
This check adds a filesystem-level scan for stale soak worktrees.

## Detection Strategy

1. List all git worktrees via `git worktree list --porcelain`.
2. For each worktree whose branch matches the soak pattern, stat its
   `.git` file (mtime) to determine age.
3. If the worktree is older than a configurable threshold, emit a `warn`.
   Otherwise emit `ok`.

A worktree is considered **fresh** (no warning) when its age is below the
threshold. This covers worktrees still in active use by a running soak.

A worktree is **stale** when its age exceeds the threshold. The operator
can then run `chimera doctor --fix` (or a manual `git worktree remove`)
to clean it up.

## `_check_orphan_worktrees` Function

### Proposed Signature

```python
def _check_orphan_worktrees(
    state_dir: Path,
    worktree_age_hours: float = 24.0,
) -> CheckResult:
```

`worktree_age_hours` defaults to the env-var `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS`
(parsed as float, default 24.0). The function:

- runs `git worktree list --porcelain` and parses the output
- for each worktree whose branch matches the soak pattern, computes
  `time.time() - os.path.getmtime(wt_path / ".git")` -> age seconds
- converts to hours; if age > `worktree_age_hours`, adds the worktree
  path to the warning details
- returns `ok` if no stale soak worktrees found, `warn` otherwise

### Soak-Branch Pattern

```python
import re
re.match(r"^chimera-soak/v\d+-", branch)
```

This matches branches like `chimera-soak/v9-test`,
`chimera-soak/v10-remediation`, `chimera-soak/v5-multi-agent`, etc.
It is a superset of the pattern in `chimera/core/submit_pr.py:22`
(which uses `^chimera-soak/v\d+(?:[-_/].+)?$`) -- the doctor check is
deliberately narrower: it requires the trailing `-` after the version
number to reduce false positives on manually created branches that happen
to start with `chimera-soak/v`.

### Age-Threshold Env Knob

| Env var | Type | Default | Description |
|---|---|---|---|
| `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS` | float | 24.0 | Hours after which a soak worktree is considered orphaned/stale |

### Wiring

In `run_checks()` (circa line 152 of `chimera/core/doctor.py`), add a
call:

```python
_check_orphan_worktrees(state_dir),
```

alongside the existing checks. The `worktree_age_hours` threshold is read
from the env var at call time, not at import time, so the operator can
tweak it without restarting.

## Pseudocode Test

```python
def test_orphan_worktree_fresh_vs_stale(
    monkeypatch, tmp_path: Path,
) -> None:
    """v4.XX: a worktree under the age threshold -> ok;
    an aged soak worktree -> warn."""
    import os
    import time
    from pathlib import Path
    from chimera.core.doctor import _check_orphan_worktrees

    # --- Setup: fake `git worktree list --porcelain` output ---
    fresh_wt = tmp_path / "worktrees" / "soak-fresh"
    stale_wt = tmp_path / "worktrees" / "soak-stale"
    non_soak_wt = tmp_path / "worktrees" / "feature-foo"
    for d in (fresh_wt, stale_wt, non_soak_wt):
        d.mkdir(parents=True, exist_ok=True)
        (d / ".git").write_text("gitdir: /fake/gitdir\n")

    # Stale worktree: use mtime far in the past.
    old_mtime = time.time() - (48 * 3600)  # 48 hours ago
    os.utime(stale_wt / ".git", (old_mtime, old_mtime))

    # Fresh worktree: mtime is now (default).

    import subprocess as _sp

    porcelain_lines = (
        f"worktree {fresh_wt}\n"
        "HEAD abcdef1\n"
        "branch refs/heads/chimera-soak/v9-fresh\n"
        "\n"
        f"worktree {stale_wt}\n"
        "HEAD 1234567\n"
        "branch refs/heads/chimera-soak/v9-stale\n"
        "\n"
        f"worktree {non_soak_wt}\n"
        "HEAD fedcba9\n"
        "branch refs/heads/feature/foo\n"
        "\n"
    )

    def fake_run(*args, **kwargs):
        return _sp.CompletedProcess(
            args=args, returncode=0,
            stdout=porcelain_lines, stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    # --- Case 1: age threshold 1 hour -> stale should be warn ---
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)

    r = _check_orphan_worktrees(state_dir, worktree_age_hours=1.0)
    assert r.status == "warn", f"expected warn, got {r.status}: {r.message}"
    assert "chimera-soak/v9-stale" in r.message or str(stale_wt) in r.message

    # --- Case 2: age threshold 72 hours -> stale is 48h, under threshold -> ok ---
    r2 = _check_orphan_worktrees(state_dir, worktree_age_hours=72.0)
    assert r2.status == "ok", f"expected ok, got {r2.status}: {r2.message}"

    # --- Case 3: no soak worktrees at all -> ok ---
    no_soak_lines = (
        f"worktree {non_soak_wt}\n"
        "HEAD fedcba9\n"
        "branch refs/heads/feature/foo\n"
        "\n"
    )

    def fake_run_no_soak(*args, **kwargs):
        return _sp.CompletedProcess(
            args=args, returncode=0,
            stdout=no_soak_lines, stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run_no_soak)
    r3 = _check_orphan_worktrees(state_dir, worktree_age_hours=1.0)
    assert r3.status == "ok"
```

The test:
- creates three fake worktree dirs (fresh soak, stale soak, non-soak)
- fakes `subprocess.run` to return `git worktree list --porcelain` output
- verifies that a 48-hour-old soak worktree triggers `warn` at a 1-hour threshold
- verifies the same worktree is `ok` at a 72-hour threshold
- verifies that non-soak worktrees are never flagged

## READY-FOR-REMEDIATION

(a) `def _check_orphan_worktrees(state_dir: Path, worktree_age_hours: float = 24.0) -> CheckResult:`

(b) `re.match(r"^chimera-soak/v\d+-", branch)`

(c) `CHIMERA_DOCTOR_WORKTREE_AGE_HOURS` (float, default 24.0)

(d) Pseudocode test: `test_orphan_worktree_fresh_vs_stale` -- creates a 48-hour-old soak worktree and a current worktree, mocks `git worktree list --porcelain` output, asserts `ok` for fresh/non-soak worktrees and `warn` for the aged soak worktree.