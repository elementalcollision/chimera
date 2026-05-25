# v31 Doctor Detector — Design Spec

## Context

**Sub-soak A** of the chip-branch-jump prevention composed wiring
(v31–v33).  The papercut: chip sessions sometimes check out their
feature branch into the operator's main worktree (e.g.
`/Users/dave/uberagent`) instead of a fresh path, polluting main with
in-progress chip changes.  Hit 3+ times.

This soak ships the **detector** (layer 1 of 3).  Layers 2 (pre-spawn
hook) and 3 (post-commit logger) follow in v32 and v33.

## Detection Logic

```
if cwd == `git rev-parse --show-toplevel`  (we are in the main worktree root)
   AND  `git rev-parse --abbrev-ref HEAD` != "main"
       → warning ("you are on branch X in the main worktree; chip changes will pollute main")
else → ok
```

Status is `warn`, NEVER `error` — false positives must not break
startup.  Defensive: any git/filesystem exception → `ok` ("cannot determine").

## Template

`_check_orphan_worktrees` in `chimera/core/doctor.py` (~line 389)
is the shape to copy.  It:
- Imports `re`, `datetime`, `timezone` locally (not module-top)
- Defensive `try`/`except` wrapping every git/filesystem read
- Returns `CheckResult("name", "ok"|"warn"|"error", "message")`
- Never raises on benign input

## Placement

The new function goes immediately after `_check_orphan_worktrees`
(before `_check_soak_runner_liveness`).  Registration goes in
`run_checks()`, right after the `_check_orphan_worktrees` call.

## Function Signature

```python
def _check_main_worktree_branch_drift(repo_root: Path) -> CheckResult:
```

## Exact Function Body

```python
def _check_main_worktree_branch_drift(repo_root: Path) -> CheckResult:
    """Detect when a chip session has checked out a non-main branch
    in the operator's main worktree, polluting main with in-progress
    chip changes (chip-branch-jump papercut, layer 1/3).

    Returns ``warn`` when cwd is the git toplevel AND the checked-out
    branch is not ``main``.  Returns ``ok`` otherwise, including on
    any git/filesystem error (false positives are worse than missed
    detections).
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
            cwd=str(repo_root), timeout=5.0,
        )
    except (subprocess.SubprocessError, OSError):
        return CheckResult("worktree_branch_drift", "ok", "cannot run git rev-parse")

    if result.returncode != 0:
        return CheckResult("worktree_branch_drift", "ok", "git rev-parse failed (not a repo?)")

    toplevel = Path(result.stdout.strip()).resolve()
    cwd = repo_root.resolve()

    if cwd != toplevel:
        return CheckResult(
            "worktree_branch_drift", "ok",
            f"cwd {cwd} ≠ git toplevel {toplevel}; not the main worktree",
        )

    try:
        result2 = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
            cwd=str(repo_root), timeout=5.0,
        )
    except (subprocess.SubprocessError, OSError):
        return CheckResult("worktree_branch_drift", "ok", "cannot read HEAD branch")

    if result2.returncode != 0:
        return CheckResult("worktree_branch_drift", "ok", "git rev-parse HEAD failed (detached?)")

    branch = result2.stdout.strip()

    if branch == "HEAD":
        return CheckResult("worktree_branch_drift", "ok", "detached HEAD at toplevel; ok")

    if branch == "main":
        return CheckResult("worktree_branch_drift", "ok", f"main worktree on main ({toplevel})")

    return CheckResult(
        "worktree_branch_drift", "warn",
        f"main worktree ({toplevel}) is on branch '{branch}', not main. "
        "Chip sessions may pollute main with in-progress changes. "
        "Switch back: `git checkout main`.",
    )
```

## Registration Line in `run_checks()`

After `_check_orphan_worktrees(Path.cwd()),` add:

```python
        _check_main_worktree_branch_drift(Path.cwd()),
```

Both take the same argument (`Path.cwd()`).

## Test Assertions

File: `tests/test_doctor.py`.  Add after the orphan-worktree test block
(~line 421).  Pattern mirrors existing tests: a helper that monkeysets
`subprocess.run`, then asserts on the returned CheckResult.

### Helper

```python
def _drift_check(monkeypatch, rev_parse_stdout, head_stdout,
                 rev_parse_rc=0, head_rc=0):
    """Call _check_main_worktree_branch_drift with mocked git subprocess."""
    import subprocess as _subprocess

    def fake_run(*args, **kwargs):
        if "--show-toplevel" in (args[0] if args else []):
            return _subprocess.CompletedProcess(
                args=args, returncode=rev_parse_rc,
                stdout=rev_parse_stdout, stderr="",
            )
        else:
            return _subprocess.CompletedProcess(
                args=args, returncode=head_rc,
                stdout=head_stdout, stderr="",
            )

    monkeypatch.setattr("subprocess.run", fake_run)
    from chimera.core.doctor import _check_main_worktree_branch_drift
    return _check_main_worktree_branch_drift(Path.cwd())
```

### Test: cwd == toplevel AND branch == main → ok

```python
def test_worktree_branch_drift_ok_when_on_main(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="main\n")
    assert r.status == "ok"
```

### Test: cwd == toplevel AND branch != main → warn

```python
def test_worktree_branch_drift_warns_when_on_feature_branch(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="chip/v31-fix\n")
    assert r.status == "warn"
    assert "chip/v31-fix" in r.message
    assert "git checkout main" in r.message
```

### Test: cwd != toplevel (i.e. in a worktree) → ok

```python
def test_worktree_branch_drift_ok_when_in_worktree_not_toplevel(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout="/some/other/worktree/path\n",
        head_stdout="chimera-soak/v31-xyz\n")
    assert r.status == "ok"
    assert "≠ git toplevel" in r.message
```

### Test: git not available → ok (never raises)

```python
def test_worktree_branch_drift_ok_when_git_fails(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout="", rev_parse_rc=128,
        head_stdout="")
    assert r.status == "ok"
```

### Test: detached HEAD → ok

```python
def test_worktree_branch_drift_ok_when_detached_head(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="HEAD\n")
    assert r.status == "ok"
    assert "detached" in r.message
```

### Test: in registry (run_checks includes it)

```python
def test_worktree_branch_drift_in_registry(monkeypatch):
    from chimera.core.doctor import CheckResult as _CR
    import chimera.core.doctor as _doctor
    sentinel = _CR("worktree_branch_drift", "ok", "sentinel")
    monkeypatch.setattr(_doctor, "_check_main_worktree_branch_drift", lambda _: sentinel)
    results = run_checks()
    assert sentinel in results
```

## Summary

| Item | Count |
|---|---|
| New function | 1 (`_check_main_worktree_branch_drift`) |
| Lines of function body | ~45 lines |
| Registration line in `run_checks()` | 1 line |
| New tests | 6 |
| Files touched | 2 (`chimera/core/doctor.py`, `tests/test_doctor.py`) |
| New dependencies | 0 (stdlib only: `subprocess`, `Path`) |
| Env knobs | 0 |

## READY-FOR-REMEDIATION

Under this heading:
(a) Exact function signature + body to insert (see "Exact Function Body" above).
(b) Registration line in `run_checks()`: `_check_main_worktree_branch_drift(Path.cwd()),`
    after `_check_orphan_worktrees(Path.cwd()),`.
(c) Test assertions (see "Test Assertions" section above):
    - cwd==repo_root+branch=main → ok
    - cwd==repo_root+branch!=main → warn
    - cwd!=repo_root → ok
    - git failure → ok (never raises)
    - detached HEAD → ok
    - registry check (run_checks includes it)
