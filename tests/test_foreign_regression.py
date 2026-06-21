"""No-pass-to-pass-regression gate for foreign PRs (ADR 0186 B.4i, from Phoenix)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.self_pr import _foreign_no_regression, _git_current_ref


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path, *, base="ok", head="ok") -> Path:
    """A clone-like repo: `main` has marker=<base>, soak branch HEAD has <head>.
    The regression_cmd `grep -q '^ok$' marker.txt` is GREEN iff marker == 'ok'."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "marker.txt").write_text(base + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "chimera-soak/x")
    (repo / "marker.txt").write_text(head + "\n")
    # A HEAD-only file guarantees a diff even when base == head (else the commit
    # is empty and git refuses). The regression_cmd only inspects marker.txt.
    (repo / "head_change.txt").write_text("agent change\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "head")
    return repo


_CMD = "grep -q '^ok$' marker.txt"


def test_blocks_when_base_green_head_red(tmp_path):
    # base ok (green), HEAD broken (red) → pass-to-pass regression → block.
    repo = _repo(tmp_path, base="ok", head="broken")
    assert _foreign_no_regression(repo, "main", _CMD) is False


def test_passes_when_base_green_head_green(tmp_path):
    repo = _repo(tmp_path, base="ok", head="ok")
    assert _foreign_no_regression(repo, "main", _CMD) is True


def test_skips_when_base_already_red(tmp_path):
    # No green baseline to protect → don't block on a pre-existing failure.
    repo = _repo(tmp_path, base="broken", head="broken")
    assert _foreign_no_regression(repo, "main", _CMD) is True


def test_skips_when_no_regression_cmd(tmp_path):
    repo = _repo(tmp_path, base="ok", head="broken")
    assert _foreign_no_regression(repo, "main", None) is True
    assert _foreign_no_regression(repo, "main", "   ") is True


def test_handles_dirty_tree_from_prior_gate(tmp_path):
    # gate-approved (verify_cmd) runs first and leaves uncommitted drift (uv.lock,
    # caches). A plain checkout would fail on it and the gate would skip; the
    # force-checkout must discard the drift and still detect the regression.
    repo = _repo(tmp_path, base="ok", head="broken")
    (repo / "marker.txt").write_text("locally dirtied\n")  # simulate gate drift
    (repo / "untracked_cache").write_text("junk\n")
    assert _foreign_no_regression(repo, "main", _CMD) is False
    assert _git_current_ref(repo) == "chimera-soak/x"


def test_restores_worktree_ref_after_check(tmp_path):
    # The checkout-dance (base → HEAD) must leave the worktree back on its branch.
    repo = _repo(tmp_path, base="ok", head="broken")
    before = _git_current_ref(repo)
    _foreign_no_regression(repo, "main", _CMD)
    assert _git_current_ref(repo) == before == "chimera-soak/x"
