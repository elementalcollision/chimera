"""Tests for the foreign-PR governance ledger (ADR 0186 B.4c)."""

from __future__ import annotations

from pathlib import Path

from chimera.core.foreign_pr_ledger import (
    count_foreign_prs_opened,
    governance_path,
    is_verify_cmd_reviewed,
    record_foreign_pr_opened,
    record_verify_cmd_review,
)


# ── verify_cmd review (per-repo, fail-closed gate) ──────────


def test_review_record_then_reviewed_true(tmp_path: Path):
    record_verify_cmd_review(tmp_path, "elementalcollision/claude-daemon", ts="t0")
    assert is_verify_cmd_reviewed(tmp_path, "elementalcollision/claude-daemon")


def test_reviewed_false_for_other_repo(tmp_path: Path):
    record_verify_cmd_review(tmp_path, "owner/a", ts="t0")
    assert not is_verify_cmd_reviewed(tmp_path, "owner/b")


def test_reviewed_false_when_no_ledger(tmp_path: Path):
    assert not is_verify_cmd_reviewed(tmp_path, "owner/a")  # fail-soft → False


def test_reviewed_false_for_empty_repo(tmp_path: Path):
    record_verify_cmd_review(tmp_path, "owner/a", ts="t0")
    assert not is_verify_cmd_reviewed(tmp_path, "")


# ── foreign PR count (global, approval gate) ────────────────


def test_count_zero_when_no_ledger(tmp_path: Path):
    assert count_foreign_prs_opened(tmp_path) == 0


def test_count_increments_per_recorded_pr(tmp_path: Path):
    record_foreign_pr_opened(tmp_path, "owner/a", "run-1", ts="t1")
    record_foreign_pr_opened(tmp_path, "owner/b", "run-2", ts="t2")
    assert count_foreign_prs_opened(tmp_path) == 2


def test_count_is_global_across_repos(tmp_path: Path):
    record_foreign_pr_opened(tmp_path, "owner/a", "r1", ts="t1")
    record_foreign_pr_opened(tmp_path, "owner/a", "r2", ts="t2")
    record_foreign_pr_opened(tmp_path, "owner/c", "r3", ts="t3")
    assert count_foreign_prs_opened(tmp_path) == 3


# ── kinds are distinct; fail-soft on garbage ────────────────


def test_review_record_does_not_count_as_pr(tmp_path: Path):
    record_verify_cmd_review(tmp_path, "owner/a", ts="t0")
    assert count_foreign_prs_opened(tmp_path) == 0
    record_foreign_pr_opened(tmp_path, "owner/a", "r1", ts="t1")
    assert count_foreign_prs_opened(tmp_path) == 1
    assert is_verify_cmd_reviewed(tmp_path, "owner/a")  # still reviewed


def test_failsoft_on_malformed_lines(tmp_path: Path):
    record_foreign_pr_opened(tmp_path, "owner/a", "r1", ts="t1")
    # Corrupt the ledger with a bad line + a non-dict line; reads must not raise.
    with governance_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write("[1,2,3]\n")
        fh.write('{"no_kind": true}\n')
    assert count_foreign_prs_opened(tmp_path) == 1
    assert is_verify_cmd_reviewed(tmp_path, "owner/a") is False
