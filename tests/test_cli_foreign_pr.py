"""Tests for the `chimera foreign-pr` CLI verbs (ADR 0186 B.4d)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.cli import main
from chimera.core.foreign_pr_ledger import (
    count_foreign_prs_opened,
    is_verify_cmd_reviewed,
    record_foreign_pr_opened,
)
from chimera.core.submit_pr import SubmitPrResult

REPO = "elementalcollision/claude-daemon"


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    for k in ("CHIMERA_FOREIGN_PR", "CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL",
              "CHIMERA_FOREIGN_PR_APPROVED", "CHIMERA_REPO_ALLOWLIST"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path, state


def _worktree(tmp_path: Path, *, tier: int = 4, allowed: bool = True) -> Path:
    wt = tmp_path / "clone"
    (wt / "state").mkdir(parents=True)
    (wt / "state" / "trust_state.json").write_text(json.dumps({"current_tier": tier}))
    (wt / "state" / "critic-gate-log.jsonl").write_text(
        json.dumps({"allowed": allowed}) + "\n"
    )
    return wt


# ── review / status ─────────────────────────────────────────


def test_review_marks_reviewed(env, capsys):
    tmp, state = env
    rc = main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    assert rc == 0
    assert "REVIEWED" in capsys.readouterr().out
    assert is_verify_cmd_reviewed(state, REPO)


def test_status_reports_count_and_review(env, capsys):
    tmp, state = env
    record_foreign_pr_opened(state, REPO, "r1", ts="t1")
    main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    capsys.readouterr()
    rc = main(["foreign-pr", "status", "--repo", REPO, "--state-dir", str(state)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "foreign PRs opened : 1" in out
    assert "reviewed = True" in out


# ── submit: skip paths (no git / submit_pr needed) ──────────


def test_submit_skips_when_off(env, capsys):
    tmp, state = env
    wt = _worktree(tmp)
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--state-dir", str(state)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out and "off by default" in out


def test_submit_skips_when_not_reviewed(env, capsys, monkeypatch):
    tmp, state = env
    wt = _worktree(tmp)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--state-dir", str(state)])
    assert rc == 0
    assert "not operator-reviewed" in capsys.readouterr().out


def test_submit_skips_when_needs_approval(env, capsys, monkeypatch):
    tmp, state = env
    wt = _worktree(tmp)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")  # reviewed but no approval grant
    main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    capsys.readouterr()
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--state-dir", str(state)])
    assert rc == 0
    assert "needs operator approval" in capsys.readouterr().out


# ── submit: fire path (submit_pr spied — no git/validate) ───


def test_submit_fires_when_all_gates_pass(env, capsys, monkeypatch):
    tmp, state = env
    wt = _worktree(tmp)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    capsys.readouterr()

    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return SubmitPrResult(ok=True, branch="chimera-soak/realtask-x",
                              pr_url="https://github.com/elementalcollision/claude-daemon/pull/9")

    monkeypatch.setattr("chimera.core.self_pr.submit_pr", _spy)
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--base", "main", "--run-id", "run-1", "--state-dir", str(state)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fired" in out and "pull/9" in out
    assert calls and calls[0]["foreign_repo"] == REPO and calls[0]["draft"] is True
    # The opened PR is recorded for the approval-count track record.
    assert count_foreign_prs_opened(state) == 1


def test_submit_dry_run_does_not_open_or_record(env, capsys, monkeypatch):
    tmp, state = env
    wt = _worktree(tmp)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    capsys.readouterr()

    def _spy(**kwargs):
        return SubmitPrResult(ok=True, branch="chimera-soak/realtask-x")

    monkeypatch.setattr("chimera.core.self_pr.submit_pr", _spy)
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--state-dir", str(state), "--dry-run"])
    assert rc == 0
    assert "dry-run" in capsys.readouterr().out
    assert count_foreign_prs_opened(state) == 0  # dry-run never recorded


# ── --state-dir default + edge cases (B.4d review) ──────────


def test_review_uses_config_state_dir_when_flag_omitted(env, capsys):
    # Regression for the review-caught crash: --state-dir omitted must fall back
    # to cfg.state_dir (CHIMERA_STATE_DIR), not raise NameError.
    tmp, state = env
    rc = main(["foreign-pr", "review", "--repo", REPO])  # no --state-dir
    assert rc == 0
    assert is_verify_cmd_reviewed(state, REPO)  # written to CHIMERA_STATE_DIR


def test_status_without_state_dir_or_repo(env, capsys):
    tmp, state = env
    record_foreign_pr_opened(state, REPO, "r1", ts="t1")
    rc = main(["foreign-pr", "status"])  # no --state-dir, no --repo
    assert rc == 0
    assert "foreign PRs opened : 1" in capsys.readouterr().out


def test_review_is_idempotent(env, capsys):
    tmp, state = env
    assert main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)]) == 0
    assert main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)]) == 0
    assert is_verify_cmd_reviewed(state, REPO)


def test_submit_returns_rc1_on_submit_failure(env, capsys, monkeypatch):
    tmp, state = env
    wt = _worktree(tmp)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    main(["foreign-pr", "review", "--repo", REPO, "--state-dir", str(state)])
    capsys.readouterr()

    def _fail(**kwargs):
        return SubmitPrResult(ok=False, branch="b", validation_errors=["nope"])

    monkeypatch.setattr("chimera.core.self_pr.submit_pr", _fail)
    rc = main(["foreign-pr", "submit", "--repo", REPO, "--worktree", str(wt),
               "--state-dir", str(state)])
    assert rc == 1
    assert "FAILED" in capsys.readouterr().out
    assert count_foreign_prs_opened(state) == 0  # failed PR not counted


def test_status_failsoft_on_corrupt_ledger(env, capsys):
    # An unreadable governance ledger (here: the path is a directory) must NOT
    # crash status — it fails soft to 0.
    from chimera.core.foreign_pr_ledger import governance_path
    tmp, state = env
    gp = governance_path(state)
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.mkdir()
    rc = main(["foreign-pr", "status", "--state-dir", str(state)])
    assert rc == 0
    assert "foreign PRs opened : 0" in capsys.readouterr().out
