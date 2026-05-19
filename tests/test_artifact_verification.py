"""Tests for v4.3 artifact verification (L-1, ADR 0026)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.act import check_artifacts, expected_artifacts


def test_expected_artifacts_extracts_backtick_paths():
    text = (
        "Write the result to `state/fib_validation.log` and the summary to "
        "`mind/graph_db_final.md`."
    )
    assert expected_artifacts(text) == [
        "state/fib_validation.log",
        "mind/graph_db_final.md",
    ]


def test_expected_artifacts_dedupes():
    text = "Write to `state/x.log`, then re-read `state/x.log`."
    assert expected_artifacts(text) == ["state/x.log"]


def test_expected_artifacts_ignores_unrelated_backticks():
    text = "Use `code_exec` to compute the result; no file needed."
    assert expected_artifacts(text) == []


def test_expected_artifacts_ignores_absolute_paths():
    # Only state/... or mind/... relative roots qualify.
    text = "Write to `/etc/passwd` and `state/safe.log`."
    assert expected_artifacts(text) == ["state/safe.log"]


def test_check_artifacts_returns_missing(tmp_path: Path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "exists.log").write_text("ok")
    missing = check_artifacts(
        ["state/exists.log", "state/missing.log", "mind/also_missing.md"],
        base_dir=tmp_path,
    )
    assert missing == ["state/missing.log", "mind/also_missing.md"]


def test_check_artifacts_empty_when_all_present(tmp_path: Path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "a.log").write_text("ok")
    assert check_artifacts(["state/a.log"], base_dir=tmp_path) == []
