"""End-to-end ``chimera run`` from a `git worktree add`-created secondary.

This is the *systemic-gap* test surfaced by two consecutive v35 soak
postmortems (PR #102 → ADR 0141 detector bug, PR #104 → SQLite thread
mismatch on the persistent loop). Both defects sat on the same code
path — ``chimera run`` invoked from a non-main branch in a secondary
worktree — and both shipped to main because no test ever exercised
that exact path end-to-end.

What this test does, that no prior test did:

* creates a real on-disk repo with ``git init`` + one commit,
* uses ``git worktree add`` to create a secondary on a feature branch,
* invokes ``chimera.cli.main(["run"])`` from inside that secondary,
* drives ``Loop.run_one_cycle()`` through the real
  ``run_on_persistent_loop`` background thread — i.e. SQLite is
  opened on the main thread and accessed from the loop thread,
* asserts the cycle returns 0 with no ``ProgrammingError``.

If a future regression reintroduces either the detector misfire OR
the cross-thread SQLite access OR any sibling cascading defect on
this same path, this test fails. That is the load-bearing property.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from chimera import cli as _cli


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
def secondary_worktree(tmp_path: Path) -> Path:
    """Build a real primary + secondary worktree pair on disk.

    Returns the path to the secondary worktree, checked out on
    ``chip/e2e-test`` (a non-main branch). The primary lives at
    ``tmp_path/primary`` on ``main``.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    (primary / "README.md").write_text("hello\n", encoding="utf-8")
    _git(primary, "add", "README.md")
    _git(primary, "commit", "-q", "-m", "init")
    secondary = tmp_path / "secondary"
    _git(primary, "worktree", "add", "-q", "-b", "chip/e2e-test",
         str(secondary), "main")
    return secondary


@pytest.fixture(autouse=True)
def _no_live_providers(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CHIMERA_ALLOW_MAIN_BRANCH_DRIFT", raising=False)


def test_chimera_run_from_secondary_worktree_completes_one_cycle(
    secondary_worktree: Path, tmp_path: Path, monkeypatch, capsys,
):
    """The canary: drive ``chimera run`` from a non-main branch inside
    a `git worktree add`-created secondary, end-to-end.

    Two prior cascading defects would have been caught here:

    * PR #103 — the ADR 0141 detector misfired on every secondary
      because it discriminated on ``--show-toplevel`` instead of
      ``--git-dir`` vs ``--git-common-dir``. The refusal would fire
      and the test would see exit code 2.
    * PR #104 (this chip) — ``Loop.__init__`` opens SQLite on the
      main thread; ``run_on_persistent_loop`` then calls
      ``run_one_cycle`` on the loop's background thread, where every
      ``self._db.execute(...)`` raises ``sqlite3.ProgrammingError``
      (default ``check_same_thread=True``). The cycle never completes
      and exit is non-zero (or an uncaught exception bubbles).
    """
    monkeypatch.chdir(secondary_worktree)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))

    rc = _cli.main(["run"])
    err = capsys.readouterr().err

    assert rc == 0, (
        f"chimera run failed in secondary worktree (rc={rc}). "
        f"stderr=\n{err}"
    )
    # Guard against a regression that swallows the SQLite error and
    # still exits 0 — assert the substring is absent from stderr.
    assert "ProgrammingError" not in err
    assert "SQLite objects created in a thread" not in err


def test_persistent_loop_drives_run_one_cycle_against_real_sqlite(
    tmp_path: Path, monkeypatch,
):
    """Regression for PR #104 — cross-thread SQLite access on the
    persistent loop.

    Tighter than the CLI E2E above: skips argparse + detector and
    drives ``run_on_persistent_loop(Loop.run_one_cycle())`` directly.
    Fails on current main with
    ``sqlite3.ProgrammingError: SQLite objects created in a thread
    can only be used in that same thread`` because ``Loop.__init__``
    opens the connection on the test thread while the cycle executes
    on ``chimera-async-loop``.
    """
    from chimera import _async_loop
    from chimera.core import ChimeraLoop, LoopConfig

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _async_loop._reset_for_tests()
    try:
        config = LoopConfig(
            mind_dir=tmp_path / "mind", state_dir=tmp_path / "state",
        )
        (tmp_path / "mind").mkdir()
        (tmp_path / "state").mkdir()
        loop = ChimeraLoop(config)
        try:
            report = _async_loop.run_on_persistent_loop(loop.run_one_cycle())
        finally:
            loop.close()
        assert report.cycle == 1
    finally:
        _async_loop._reset_for_tests()
