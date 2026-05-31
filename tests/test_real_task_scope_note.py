"""B1 W2 regression: the real-task soak's scope design note unblocks the
agent's own commit (ADR 0146 pre-commit scope check).

The first live real-task soak's agent self-commit was REFUSED because
`real_task_soak.sh` wrote no scope design note, so `check_commit_scope` bound to
a stale `*-design.md` left in the worktree by a prior soak (allowlist
`chimera/soak_report.py`) and rejected the staged `chimera/strcase.py` as
out-of-scope. Only the harness-autocommit fallback got through, masking it.

These tests run the runner's GENERATED note through the REAL scope check — the
exact gate that fired — so the regression cannot return silently:
  - an in-scope staged change → verdict "allow",
  - an out-of-scope staged change → ScopeCheckRefusal,
  - the fresh note wins over a stale prior-soak note (newest by mtime).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "real_task_soak.sh"


def _generated_note(task_files: str, goal: str = "fix it") -> str:
    """The scope design note the runner writes, captured from its dryrun."""
    env = dict(os.environ, TASK_DRYRUN="1", TASK_GOAL=goal, TASK_FILES=task_files)
    out = subprocess.run(
        ["bash", str(_SCRIPT)], capture_output=True, text=True, env=env,
    ).stdout
    body = out.split("--- scope design note (ADR 0146 allowlist) ---", 1)[1]
    return body.split("--- phase-1 INBOX ---", 1)[0].strip() + "\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo_with_note(tmp_path: Path, note_text: str, *, stale: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "chimera").mkdir()
    (repo / "chimera" / "strcase.py").write_text("x = 1\n")
    (repo / "chimera" / "other.py").write_text("y = 1\n")
    rd = repo / "mind" / "research"
    rd.mkdir(parents=True)
    if stale:
        (rd / "v46-old-design.md").write_text(
            "# old\n\n## READY-FOR-REMEDIATION\n\n- `chimera/soak_report.py`\n"
        )
    (rd / "realtask-x-design.md").write_text(note_text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _verdict(repo: Path):
    from chimera.core.scope_check import (
        ScopeCheckRefusal,
        check_commit_scope,
        resolve_repo_root,
    )
    root = resolve_repo_root(repo)
    try:
        return check_commit_scope(root).verdict
    except ScopeCheckRefusal:
        return "refuse"


def test_in_scope_commit_is_allowed(tmp_path):
    note = _generated_note("chimera/strcase.py")
    repo = _repo_with_note(tmp_path, note)
    (repo / "chimera" / "strcase.py").write_text("x = 2\n")
    _git(repo, "add", "chimera/strcase.py")
    assert _verdict(repo) == "allow"


def test_out_of_scope_commit_is_refused(tmp_path):
    note = _generated_note("chimera/strcase.py")
    repo = _repo_with_note(tmp_path, note)
    (repo / "chimera" / "other.py").write_text("y = 2\n")  # NOT in the allowlist
    _git(repo, "add", "chimera/other.py")
    assert _verdict(repo) == "refuse"


def test_fresh_note_wins_over_stale_prior_soak_note(tmp_path):
    # The exact W2 condition: a stale v46 note (allowlist soak_report.py) is
    # present, but the fresh real-task note must win and allow strcase.py.
    note = _generated_note("chimera/strcase.py")
    repo = _repo_with_note(tmp_path, note, stale=True)
    (repo / "chimera" / "strcase.py").write_text("x = 2\n")
    _git(repo, "add", "chimera/strcase.py")
    assert _verdict(repo) == "allow"


def test_multi_file_allowlist(tmp_path):
    note = _generated_note("chimera/strcase.py chimera/other.py")
    repo = _repo_with_note(tmp_path, note)
    (repo / "chimera" / "strcase.py").write_text("x = 2\n")
    (repo / "chimera" / "other.py").write_text("y = 2\n")
    _git(repo, "add", "chimera/strcase.py", "chimera/other.py")
    assert _verdict(repo) == "allow"
