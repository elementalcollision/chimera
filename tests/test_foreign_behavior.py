"""Behaviour-preservation differential gate for foreign PRs (ADR 0186 B.4k)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.self_pr import _foreign_behavior_preserved, _git_current_ref


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path, *, base="out", head="out") -> Path:
    """A clone-like repo: `main` has behavior.txt=<base>, the soak branch HEAD has
    <head>. The behavior_cmd `cat behavior.txt` is the characterization driver — its
    stdout is the observable behaviour. `head_change.txt` (HEAD-only) guarantees a
    non-empty diff even when base == head."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "behavior.txt").write_text(base + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "chimera-soak/x")
    (repo / "behavior.txt").write_text(head + "\n")
    (repo / "head_change.txt").write_text("agent change\n")  # HEAD-only → guarantees a diff
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "head")
    return repo


_CMD = "cat behavior.txt"


def test_blocks_when_behaviour_changed(tmp_path):
    # base prints "A", HEAD prints "B" → observable behaviour changed → block.
    repo = _repo(tmp_path, base="A", head="B")
    assert _foreign_behavior_preserved(repo, "main", _CMD) is False


def test_passes_when_behaviour_preserved(tmp_path):
    # Same driver output on both revisions (a true refactor) → proceed.
    repo = _repo(tmp_path, base="A", head="A")
    assert _foreign_behavior_preserved(repo, "main", _CMD) is True


def test_skips_when_no_behavior_cmd(tmp_path):
    repo = _repo(tmp_path, base="A", head="B")
    assert _foreign_behavior_preserved(repo, "main", None) is True
    assert _foreign_behavior_preserved(repo, "main", "   ") is True


def test_fails_open_when_driver_absent_at_base(tmp_path):
    # head_change.txt exists only on HEAD → the driver runs at HEAD but errors at
    # base (no baseline to compare) → fail-OPEN (additive assurance), don't block.
    repo = _repo(tmp_path, base="A", head="B")
    assert _foreign_behavior_preserved(repo, "main", "cat head_change.txt") is True


def test_handles_dirty_tree_from_prior_gate(tmp_path):
    # gate-approved (verify_cmd) runs first and leaves uncommitted drift; the
    # force-checkout must discard it and still detect the behaviour change.
    repo = _repo(tmp_path, base="A", head="B")
    (repo / "behavior.txt").write_text("locally dirtied\n")  # simulate gate drift
    (repo / "untracked_cache").write_text("junk\n")
    assert _foreign_behavior_preserved(repo, "main", _CMD) is False
    assert _git_current_ref(repo) == "chimera-soak/x"


def test_restores_worktree_ref_after_check(tmp_path):
    repo = _repo(tmp_path, base="A", head="B")
    before = _git_current_ref(repo)
    _foreign_behavior_preserved(repo, "main", _CMD)
    assert _git_current_ref(repo) == before == "chimera-soak/x"


def test_detached_head_restored_to_sha(tmp_path):
    repo = _repo(tmp_path, base="A", head="B")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                         capture_output=True, text=True).stdout.strip()
    _git(repo, "checkout", "-q", sha)  # detach
    assert _git_current_ref(repo) == sha
    assert _foreign_behavior_preserved(repo, "main", _CMD) is False
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                           capture_output=True, text=True).stdout.strip()
    assert after == sha  # restored to the detached commit
