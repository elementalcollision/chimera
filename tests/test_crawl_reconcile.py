"""Automated revert reconciliation — B.4l label producer (ADR 0186)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.crawl_ledger import (
    CrawlOutcome,
    detect_reverts,
    git_revert_messages,
    read_outcomes,
    reconcile_reverts,
    record_outcome,
)


def _git(repo: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True)


def _merged(run_id, slug, branch):
    return CrawlOutcome(run_id=run_id, ts="t", slug=slug, gate="pass",
                        branch=branch, disposition="merged")


# ── detect_reverts (pure, injectable) ───────────────────────────────


def test_detect_reverts_matches_slug_in_revert_subject():
    outs = [_merged("r1", "merge-rate", "chimera-soak/merge-rate"),
            _merged("r2", "ready-slugs", "chimera-soak/ready-slugs")]
    msgs = ['Revert "feat: add merge-rate helper (#42)"']
    assert detect_reverts(outs, msgs) == {"r1"}


def test_detect_reverts_empty_when_no_match_or_no_messages():
    outs = [_merged("r1", "x", "b")]
    assert detect_reverts(outs, ['Revert "something unrelated"']) == set()
    assert detect_reverts(outs, []) == set()


def test_detect_reverts_ignores_outcomes_without_needles():
    outs = [_merged("r1", "", "")]  # no slug/branch → can't match
    assert detect_reverts(outs, ['Revert "anything"']) == set()


# ── git_revert_messages + reconcile_reverts (synthetic repo) ────────


def _repo_with_revert(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "f.txt").write_text("y\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: merge-rate helper (#42)")
    _git(repo, "revert", "--no-edit", "HEAD")  # → 'Revert "feat: merge-rate helper (#42)"'
    return repo


def test_git_revert_messages_finds_the_revert(tmp_path):
    msgs = git_revert_messages(_repo_with_revert(tmp_path), "main")
    assert any(m.startswith("Revert ") and "merge-rate helper" in m for m in msgs)


def test_git_revert_messages_failsoft_on_bad_repo(tmp_path):
    assert git_revert_messages(tmp_path / "nonexistent", "main") == []


def test_reconcile_reverts_sets_disposition(tmp_path):
    repo = _repo_with_revert(tmp_path)
    state = tmp_path / "state"
    record_outcome(state, _merged("r1", "merge-rate", "chimera-soak/merge-rate"))
    newly = reconcile_reverts(state, repo, "main")
    assert newly == ["r1"]
    by_id = {o.run_id: o.disposition for o in read_outcomes(state)}
    assert by_id["r1"] == "reverted"


def test_reconcile_reverts_noop_when_nothing_merged(tmp_path):
    repo = _repo_with_revert(tmp_path)
    state = tmp_path / "state"
    record_outcome(state, CrawlOutcome(run_id="r1", ts="t", slug="merge-rate",
                                       gate="pass", branch="b", disposition="abandoned"))
    assert reconcile_reverts(state, repo, "main") == []
    # abandoned stays abandoned — only merged work is reconciled.
    assert {o.run_id: o.disposition for o in read_outcomes(state)}["r1"] == "abandoned"
