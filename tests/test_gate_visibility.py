"""Gate-visibility classifier — ADR 0182 prerequisite.

The plain `chimera verify` gate answers "is it green now?", which a task
already green on base passes without doing anything (2026-06-12 Finding 1:
a deprecation-warning "fix" that edited no file still "passed"). This
classifier adds the missing half — the gate must have been RED on base —
so the CRAWL picker can reject gate-invisible specs before dispatching the
agent.

Tests use a real git repo with a content-sensitive check (a flag file), so
the base worktree and the working tree genuinely differ — no mocking of
git or subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera.core.repo_verify import (
    BASE_ERROR,
    GREEN_TO_GREEN,
    RED_TO_GREEN,
    STILL_RED,
    classify_gate_transition,
)

# A check that passes only when `fixed.flag` exists in the cwd — so the
# verdict depends on the worktree CONTENT, not just the command.
_FLAG_CHECK = [("flag", ["sh", "-c", "test -f fixed.flag"])]
_NEVER = [("never", ["sh", "-c", "test -f does-not-exist.flag"])]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "base")  # base has NO fixed.flag
    return r


def test_red_to_green_is_gate_visible(repo: Path):
    # Working tree adds the flag the base lacks: red on base → green now.
    (repo / "fixed.flag").write_text("x")
    gv = classify_gate_transition(repo, "HEAD", checks=_FLAG_CHECK)
    assert gv.transition == RED_TO_GREEN
    assert gv.gate_visible is True
    assert "GATE-VISIBLE" in gv.summary()


def test_green_to_green_is_gate_invisible(repo: Path):
    # The flag is committed on base AND present now → the change proves
    # nothing. This is the Finding 1 class.
    (repo / "fixed.flag").write_text("x")
    _git(repo, "add", "fixed.flag")
    _git(repo, "commit", "-qm", "flag on base")
    gv = classify_gate_transition(repo, "HEAD", checks=_FLAG_CHECK)
    assert gv.transition == GREEN_TO_GREEN
    assert gv.gate_visible is False
    assert "GATE-INVISIBLE" in gv.summary()


def test_still_red_when_change_does_not_pass(repo: Path):
    gv = classify_gate_transition(repo, "HEAD", checks=_NEVER)
    assert gv.transition == STILL_RED
    assert gv.gate_visible is False
    assert "STILL-RED" in gv.summary()


def test_unknown_base_ref_is_base_error_not_raise(repo: Path):
    (repo / "fixed.flag").write_text("x")
    gv = classify_gate_transition(repo, "no-such-ref", checks=_FLAG_CHECK)
    assert gv.transition == BASE_ERROR
    assert gv.gate_visible is False
    assert gv.before is None
    assert "BASE-ERROR" in gv.summary()


def test_base_worktree_is_cleaned_up(repo: Path):
    (repo / "fixed.flag").write_text("x")
    classify_gate_transition(repo, "HEAD", checks=_FLAG_CHECK)
    # No leftover linked worktrees beyond the primary.
    out = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out.strip().count("\n") == 0, f"leftover worktrees:\n{out}"


def test_after_failure_short_circuits_to_still_red(repo: Path):
    # Even if base would be red, an unfixed worktree is STILL_RED, never
    # mislabelled gate-visible.
    gv = classify_gate_transition(repo, "HEAD", checks=_NEVER)
    assert gv.transition == STILL_RED
