"""ADR 0148: harness-executed deterministic commit for soak phase 2.

The v46 re-soak #2 confirmed the ADR 0147 commit-not-executed gate fires
in-loop but does NOT drive convergence — the agent stages + greens then refuses
to run `git commit` (58 firings, no commit). This module takes the commit out of
the agent's hands. These tests pin every status path against a real temp repo.
"""

from __future__ import annotations

import subprocess

from chimera.soak_autocommit import (
    ALREADY_COMMITTED,
    COMMITTED,
    NOTHING_TO_COMMIT,
    TEST_FAILING,
    autocommit_if_ready,
)

MSG = "[agent] create chimera/soak_report.py (harness-committed per ADR 0148)"
PASS_CMD = ["true"]
FAIL_CMD = ["false"]


def _git(root, *args) -> None:
    subprocess.run(
        ["git", *args], cwd=str(root), check=True,
        capture_output=True, text=True,
    )


def _init_repo(root) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-qm", "seed")
    # Diverge onto a soak branch so main..HEAD has meaning.
    _git(root, "checkout", "-q", "-b", "soak")


def _agent_subjects(root):
    out = subprocess.run(
        ["git", "log", "--format=%s", "main..HEAD"], cwd=str(root),
        capture_output=True, text=True,
    )
    return [s for s in out.stdout.splitlines() if s.startswith("[agent]")]


def test_commits_when_staged_and_green(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    status = autocommit_if_ready(
        tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD,
    )
    assert status == COMMITTED
    # An [agent] commit now exists, and it carries the deliverable.
    assert _agent_subjects(tmp_path) == [MSG]
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert "deliverable.py" in show.stdout


def test_idempotent_when_agent_commit_exists(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    assert autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == COMMITTED
    # Second call: nothing new, [agent] commit already present → no-op.
    (tmp_path / "deliverable.py").write_text("x = 2\n")
    assert autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == ALREADY_COMMITTED
    # Still exactly one [agent] commit.
    assert len(_agent_subjects(tmp_path)) == 1


def test_never_commits_red_code(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    status = autocommit_if_ready(
        tmp_path, ["deliverable.py"], MSG, test_cmd=FAIL_CMD,
    )
    assert status == TEST_FAILING
    assert _agent_subjects(tmp_path) == []


def test_nothing_to_commit_when_no_deliverable(tmp_path):
    _init_repo(tmp_path)
    # allowed file absent, no journal dir → nothing staged.
    status = autocommit_if_ready(
        tmp_path, ["absent.py"], MSG, test_cmd=PASS_CMD,
    )
    assert status == NOTHING_TO_COMMIT
    assert _agent_subjects(tmp_path) == []


def test_stages_journal_tree(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "mind").mkdir()
    (tmp_path / "mind" / "CHRONICLE.md").write_text("log\n")
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    assert autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == COMMITTED
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert "deliverable.py" in show.stdout
    assert "mind/CHRONICLE.md" in show.stdout


def test_skips_test_when_no_cmd(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    # test_cmd=None → commit without running any test.
    assert autocommit_if_ready(tmp_path, ["deliverable.py"], MSG) == COMMITTED


def test_only_stages_allowed_files_not_unrelated(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    (tmp_path / "rogue.py").write_text("evil = 1\n")  # NOT in allowed_files
    assert autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == COMMITTED
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert "deliverable.py" in show.stdout
    assert "rogue.py" not in show.stdout  # unrelated file left untracked


def test_fail_safe_on_non_repo(tmp_path):
    # No git repo → _has_agent_commit False, then add/commit fail → ERROR or
    # nothing-to-commit, never a raise.
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    status = autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD)
    assert status in {"error", NOTHING_TO_COMMIT}


# ── ADR 0162: the critic gate also guards the harness autocommit path ──


def test_autocommit_blocked_by_critic_gate_when_enforced(tmp_path, monkeypatch):
    import chimera.core.critic_gate as cg
    from chimera.soak_autocommit import CRITIC_BLOCKED

    monkeypatch.setenv("CHIMERA_CRITIC_ENFORCE", "1")
    monkeypatch.delenv("CHIMERA_ALLOW_CRITIC_REJECT", raising=False)
    monkeypatch.setattr(cg, "_build_reviewer", lambda *a, **k: None)  # fail-closed
    cg.write_calibration_record(tmp_path, total=27, false_approve=0,
                                false_reject=3, accuracy=0.89)
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    status = autocommit_if_ready(tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD)
    assert status == CRITIC_BLOCKED
    assert _agent_subjects(tmp_path) == []  # no commit landed


def test_autocommit_proceeds_with_override(tmp_path, monkeypatch):
    import chimera.core.critic_gate as cg

    monkeypatch.setenv("CHIMERA_CRITIC_ENFORCE", "1")
    monkeypatch.setenv("CHIMERA_ALLOW_CRITIC_REJECT", "1")  # operator override
    monkeypatch.setattr(cg, "_build_reviewer", lambda *a, **k: None)
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    assert autocommit_if_ready(
        tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == COMMITTED


def test_autocommit_inert_when_not_enforced(tmp_path, monkeypatch):
    import chimera.core.critic_gate as cg

    monkeypatch.delenv("CHIMERA_CRITIC_ENFORCE", raising=False)
    monkeypatch.setattr(cg, "_build_reviewer", lambda *a, **k: None)
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    assert autocommit_if_ready(
        tmp_path, ["deliverable.py"], MSG, test_cmd=PASS_CMD) == COMMITTED
