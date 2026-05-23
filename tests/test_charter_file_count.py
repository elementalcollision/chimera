"""v4.116 (ADR 0116): charter file-count enforcement.

Soak v20-relaunch landed an [agent] commit whose phase-2 INBOX charter
said:

    SCOPE: ONE new function, `check_ruff_claim_valid`, in
    `chimera/core/act.py`. ONE new test file,
    `tests/test_ruff_claim_invalid.py`. NO third file.

The actual cumulative diff vs ``main`` carried ``chimera/core/act.py``
plus ``mind/research/ruff-claim-design.md`` (third file, out of
charter) and was missing ``tests/test_ruff_claim_invalid.py``
(required by charter). The witness panel approved on semantics; no
platform-side gate compared the committed file set against the
charter's enumeration.

This module tests
:func:`chimera.core.witness.extract_charter_file_enumeration` and
:func:`chimera.core.witness.check_charter_file_count`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.witness import (
    check_charter_file_count,
    extract_charter_file_enumeration,
)


def _git(*args: str, cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, check=True,
    )
    return res.stdout


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("base\n")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "initial", cwd=root)
    _git("checkout", "-q", "-b", "feat/x", cwd=root)


# ── extract_charter_file_enumeration ───────────────────────────


def test_extract_picks_up_two_files_charter() -> None:
    task = (
        "CHARTER for phase 2:\n"
        "  1. SCOPE: ONE new function in `chimera/core/act.py`.\n"
        "     ONE new test file, `tests/test_ruff_claim_invalid.py`.\n"
        "     NO third file.\n"
    )
    assert extract_charter_file_enumeration(task) == [
        "chimera/core/act.py",
        "tests/test_ruff_claim_invalid.py",
    ]


def test_extract_dedupes_repeated_paths() -> None:
    task = (
        "CHARTER:\n"
        "  Edit `chimera/core/act.py`. Then re-edit `chimera/core/act.py`.\n"
        "  Add `tests/test_foo.py`.\n"
    )
    assert extract_charter_file_enumeration(task) == [
        "chimera/core/act.py",
        "tests/test_foo.py",
    ]


def test_extract_ignores_bare_or_unrooted_paths() -> None:
    """No backticks / no rooted prefix → not part of the enumeration."""
    task = (
        "CHARTER:\n"
        "  Edit chimera/core/act.py (bare). Touch `foo.py` (unrooted).\n"
        "  Touch `chimera/core/` (no extension).\n"
    )
    assert extract_charter_file_enumeration(task) == []


def test_extract_empty_without_charter_block() -> None:
    task = "Please add `chimera/core/act.py` to the project."  # no CHARTER
    assert extract_charter_file_enumeration(task) == []


def test_extract_empty_for_empty_text() -> None:
    assert extract_charter_file_enumeration("") == []


# ── check_charter_file_count ───────────────────────────────────


_CHARTER_TWO_FILES = (
    "CHARTER for phase 2:\n"
    "  SCOPE: ONE new function in `chimera/core/act.py`.\n"
    "  ONE new test file, `tests/test_ruff_claim_invalid.py`.\n"
    "  NO third file.\n"
)


def _agent_commit(root: Path, paths: list[str], body: str = "work") -> None:
    for p in paths:
        full = root / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("x\n")
        _git("add", p, cwd=root)
    _git(
        "commit", "-q", "-m",
        f"[agent] {body}",
        cwd=root,
    )


def test_no_enumeration_is_silent(tmp_path: Path) -> None:
    """Charter with no backticked rooted paths → no constraint to enforce."""
    _init_repo(tmp_path)
    _agent_commit(tmp_path, ["chimera/core/act.py", "anything/else.py"])
    assert check_charter_file_count("free-form task text", tmp_path) == []


def test_diff_matches_charter_exactly(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        ["chimera/core/act.py", "tests/test_ruff_claim_invalid.py"],
    )
    assert check_charter_file_count(_CHARTER_TWO_FILES, tmp_path) == []


def test_diff_carries_unsanctioned_third_file(tmp_path: Path) -> None:
    """The v20-relaunch failure shape."""
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "mind/research/ruff-claim-design.md",
        ],
    )
    violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)
    assert violations == ["mind/research/ruff-claim-design.md"]


def test_remediation_doc_auto_allowed(tmp_path: Path) -> None:
    """soak_lib v2 convention: *-remediation.md is always allowed."""
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "tests/test_ruff_claim_invalid.py",
            "mind/research/ruff-claim-remediation.md",
        ],
    )
    assert check_charter_file_count(_CHARTER_TWO_FILES, tmp_path) == []


def test_operator_commit_is_silent(tmp_path: Path) -> None:
    """No [agent] prefix → out of scope for the contract."""
    _init_repo(tmp_path)
    p = tmp_path / "mind" / "research" / "drive-by.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("operator note\n")
    _git("add", "mind/research/drive-by.md", cwd=tmp_path)
    _git("commit", "-q", "-m", "operator drive-by", cwd=tmp_path)
    assert check_charter_file_count(_CHARTER_TWO_FILES, tmp_path) == []


def test_subprocess_failure_returns_empty(tmp_path: Path) -> None:
    """Non-repo path → git errors → empty (false-positives are worse)."""
    (tmp_path / "not-a-repo").mkdir()
    assert check_charter_file_count(
        _CHARTER_TWO_FILES, tmp_path / "not-a-repo",
    ) == []


def test_violations_dedupe_when_diff_lists_duplicate(tmp_path: Path) -> None:
    """Defensive: even if diff somehow lists a path twice, return one."""
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        ["chimera/core/act.py", "chimera/core/extra.py"],
    )
    violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)
    assert violations == ["chimera/core/extra.py"]
