"""ADR 0141 Layer 2 — `chimera run` refuses chip-branch-jumped state.

Mirrors the monkeypatched-subprocess pattern from
``tests/test_doctor.py::_drift_check``. Drives the CLI via
``chimera.cli.main`` so we exercise the actual argparse + refusal path,
not just the underlying detector (which is covered by Layer 1 tests).
"""

from __future__ import annotations

import subprocess as _subprocess

import pytest

from chimera import cli as _cli


def _patch_git(monkeypatch, *, toplevel: str, branch: str,
               toplevel_rc: int = 0, branch_rc: int = 0,
               git_dir: str = ".git", git_common_dir: str = ".git") -> None:
    """Patch subprocess.run so the in-process drift detector sees the
    given (toplevel, branch, git-dir, git-common-dir) without touching
    the real repo state.

    Defaults reflect a primary worktree where git-dir == git-common-dir.
    To simulate a `git worktree add`-ed secondary, pass differing values.
    See chimera/core/doctor.py:detect_main_worktree_branch_drift for
    why this is the correct discriminator (v35 soak postmortem, 2026-05-28).
    """
    def fake_run(*args, **kwargs):
        argv = args[0] if args else []
        if "--show-toplevel" in argv:
            return _subprocess.CompletedProcess(
                args=argv, returncode=toplevel_rc,
                stdout=toplevel + "\n", stderr="",
            )
        if "--git-dir" in argv:
            return _subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=git_dir + "\n", stderr="",
            )
        if "--git-common-dir" in argv:
            return _subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=git_common_dir + "\n", stderr="",
            )
        return _subprocess.CompletedProcess(
            args=argv, returncode=branch_rc,
            stdout=branch + "\n", stderr="",
        )
    monkeypatch.setattr("subprocess.run", fake_run)


@pytest.fixture
def isolated_run(monkeypatch, tmp_path):
    """Run from an isolated cwd so the detector's `Path.cwd()` matches
    the patched git toplevel — and so a real `ChimeraLoop()` would not
    be constructed (the refusal returns before that)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CHIMERA_ALLOW_MAIN_BRANCH_DRIFT", raising=False)
    return tmp_path


def test_run_refuses_when_main_worktree_on_feature_branch(
    isolated_run, monkeypatch, capsys,
):
    _patch_git(monkeypatch, toplevel=str(isolated_run), branch="feat/chip-foo")
    rc = _cli.main(["run"])
    captured = capsys.readouterr()
    assert rc == 2, f"expected exit 2, got {rc}; stderr={captured.err!r}"
    assert "chimera run refuses" in captured.err
    assert "feat/chip-foo" in captured.err
    assert "CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1" in captured.err
    assert "git worktree add" in captured.err


def test_run_allowed_when_override_env_set(
    isolated_run, monkeypatch,
):
    _patch_git(monkeypatch, toplevel=str(isolated_run), branch="feat/chip-foo")
    monkeypatch.setenv("CHIMERA_ALLOW_MAIN_BRANCH_DRIFT", "1")

    # ChimeraLoop construction would happen; stub it so we don't need a
    # live state dir. Verify the stub IS reached (refusal bypassed).
    called = {"n": 0}

    class _StubLoop:
        def __init__(self):
            called["n"] += 1

        async def run_one_cycle(self):
            from chimera.core import CycleReport
            called["n"] += 1
            return CycleReport(
                cycle=0, started_at="t0", completed_at="t1",
                tasks_seen=0, tasks_completed=0,
                rotated=False, phase_log=[], phase_times_ms={},
            )

        def close(self):
            pass

    monkeypatch.setattr("chimera.core.ChimeraLoop", _StubLoop)
    rc = _cli.main(["run"])
    assert rc == 0, "expected stub-driven run to succeed past the override"
    assert called["n"] >= 1, "ChimeraLoop should have been constructed"


def test_run_allowed_when_on_main(isolated_run, monkeypatch):
    _patch_git(monkeypatch, toplevel=str(isolated_run), branch="main")

    class _StubLoop:
        def __init__(self):
            pass

        async def run_one_cycle(self):
            from chimera.core import CycleReport
            return CycleReport(
                cycle=0, started_at="t0", completed_at="t1",
                tasks_seen=0, tasks_completed=0,
                rotated=False, phase_log=[], phase_times_ms={},
            )

        def close(self):
            pass

    monkeypatch.setattr("chimera.core.ChimeraLoop", _StubLoop)
    rc = _cli.main(["run"])
    assert rc == 0


def test_run_allowed_in_secondary_worktree(isolated_run, monkeypatch):
    # Secondary `git worktree add`-ed worktree: git-dir != git-common-dir.
    # Even on a non-main branch, the detector must allow chimera run here.
    # Regression: see mind/research/v35-soak-postmortem-2026-05-28.md —
    # the previous --show-toplevel-based discriminator misfired here and
    # refused every soak iteration.
    _patch_git(
        monkeypatch, toplevel=str(isolated_run), branch="feat/chip-foo",
        git_dir="/path/to/main/.git/worktrees/secondary",
        git_common_dir="/path/to/main/.git",
    )

    class _StubLoop:
        def __init__(self):
            pass

        async def run_one_cycle(self):
            from chimera.core import CycleReport
            return CycleReport(
                cycle=0, started_at="t0", completed_at="t1",
                tasks_seen=0, tasks_completed=0,
                rotated=False, phase_log=[], phase_times_ms={},
            )

        def close(self):
            pass

    monkeypatch.setattr("chimera.core.ChimeraLoop", _StubLoop)
    rc = _cli.main(["run"])
    assert rc == 0


def test_run_refusal_message_includes_recovery_steps(
    isolated_run, monkeypatch, capsys,
):
    _patch_git(monkeypatch, toplevel=str(isolated_run), branch="feat/abc")
    rc = _cli.main(["run"])
    assert rc == 2
    err = capsys.readouterr().err
    for needle in (
        "git stash push",
        "git checkout main",
        "git worktree add",
        "git stash pop",
    ):
        assert needle in err, f"missing recovery step: {needle!r}"
