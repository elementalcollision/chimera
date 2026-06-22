"""Property/fuzz gate for foreign PRs (ADR 0186 B.4k stage 2b)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.self_pr import _foreign_property_holds


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    """A minimal repo at HEAD. The property gate is HEAD-only (no checkout dance):
    `grep -q '^ok$' marker.txt` PASSES, a non-matching grep FAILS."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "marker.txt").write_text("ok\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "x")
    return repo


def test_passes_when_property_holds(tmp_path):
    repo = _repo(tmp_path)
    assert _foreign_property_holds(repo, "grep -q '^ok$' marker.txt") is True


def test_blocks_when_property_fails(tmp_path):
    # A property/fuzz test that exits nonzero (a counterexample) → block.
    repo = _repo(tmp_path)
    assert _foreign_property_holds(repo, "grep -q '^NOPE$' marker.txt") is False


def test_skips_when_no_property_cmd(tmp_path):
    repo = _repo(tmp_path)
    assert _foreign_property_holds(repo, None) is True
    assert _foreign_property_holds(repo, "   ") is True
