"""v46 R2 (ADR 0147): commit-not-executed gate.

The v46 re-soak confirmed the scope_evasion commit-phase fix (#180) and, with
that mask removed, isolated "Problem B": the phase-2 commit task self-reported
completed=True after ``git add``, but ``git commit`` never ran — the deliverable
sat STAGED-but-uncommitted and the run idled to no convergence. Every existing
commit gate assumes a commit happened; this one catches a commit that was
instructed but skipped. These tests pin the trigger heuristic, the soak-scoping
no-op, the fire case, the satisfied case, and fail-open behaviour.
"""

from __future__ import annotations

import subprocess

from chimera.core.act import (
    _task_demands_agent_commit,
    check_commit_not_executed,
)

# The exact phase-2 INBOX commit task (the v46 charter wording).
PHASE2_TASK = (
    "Commit with a message starting with `[agent]` "
    "(e.g. `[agent] create chimera/soak_report.py`)."
)
# A phase-1 build task — names a path, no [agent] commit contract.
BUILD_TASK = "Build `chimera/soak_report.py` and prove green by running pytest."


def _git(root, *args) -> None:
    subprocess.run(
        ["git", *args], cwd=str(root), check=True,
        capture_output=True, text=True,
    )


def _init_repo(root) -> None:
    """A minimal repo on branch ``main`` with one base commit."""
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("base\n")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-qm", "base")


# ── _task_demands_agent_commit: the trigger heuristic ───────────────


def test_demands_commit_positive_phase2_task():
    assert _task_demands_agent_commit(PHASE2_TASK) is True


def test_demands_commit_negative_build_task():
    # No [agent] token → not the commit contract.
    assert _task_demands_agent_commit(BUILD_TASK) is False


def test_demands_commit_negative_agent_token_without_commit_verb():
    # [agent] present but no 'commit' imperative → not a commit task.
    assert _task_demands_agent_commit(
        "Stage the file and reference `[agent]` provenance in the postmortem."
    ) is False


def test_demands_commit_empty():
    assert _task_demands_agent_commit("") is False


def test_demands_commit_inflections():
    assert _task_demands_agent_commit("[agent] — do not leave it uncommitted; commit it.") is True
    assert _task_demands_agent_commit("Once committed under `[agent]`, stop.") is True


# ── check_commit_not_executed ───────────────────────────────────────


def test_none_root_is_noop_off_soak():
    # Off-soak the scan root is None → never forced to commit.
    assert check_commit_not_executed(PHASE2_TASK, None) == []


def test_non_commit_task_passes(tmp_path):
    _init_repo(tmp_path)
    assert check_commit_not_executed(BUILD_TASK, tmp_path) == []


def test_fires_when_commit_demanded_but_absent(tmp_path):
    """Problem B reproduction: HEAD == main, no [agent] commit, task
    demanded one. The gate fires.
    """
    _init_repo(tmp_path)
    out = check_commit_not_executed(PHASE2_TASK, tmp_path)
    assert len(out) == 1
    assert "[agent] commit" in out[0]
    assert "main..HEAD" in out[0]


def test_fires_even_with_staged_uncommitted_work(tmp_path):
    """The exact v46-B signature: files git-add'd but never committed."""
    _init_repo(tmp_path)
    (tmp_path / "chimera_soak_report.py").write_text("x = 1\n")
    _git(tmp_path, "add", "chimera_soak_report.py")
    # Staged but not committed → still no [agent] commit → fires.
    assert len(check_commit_not_executed(PHASE2_TASK, tmp_path)) == 1


def test_passes_when_agent_commit_landed(tmp_path):
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "-b", "work")
    (tmp_path / "g.txt").write_text("g\n")
    _git(tmp_path, "add", "g.txt")
    _git(tmp_path, "commit", "-qm", "[agent] create g")
    assert check_commit_not_executed(PHASE2_TASK, tmp_path) == []


def test_non_agent_commit_does_not_satisfy(tmp_path):
    """A plain (non-[agent]) commit — e.g. the operator strip commit in the
    re-soak — does NOT satisfy the contract."""
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "-b", "work")
    (tmp_path / "g.txt").write_text("g\n")
    _git(tmp_path, "add", "g.txt")
    _git(tmp_path, "commit", "-qm", "strip targets for re-soak rebuild")
    assert len(check_commit_not_executed(PHASE2_TASK, tmp_path)) == 1


def test_fail_open_on_non_repo(tmp_path):
    # Not a git repo (or main ref absent) → git errors → fail-open [].
    assert check_commit_not_executed(PHASE2_TASK, tmp_path) == []
