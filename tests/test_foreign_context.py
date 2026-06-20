"""Tests for the foreign-repo context block (ADR 0186 B.3b)."""

from __future__ import annotations

from pathlib import Path

from chimera.core.foreign_context import (
    foreign_context_block,
    repo_readme_excerpt,
)


# ── repo_readme_excerpt ─────────────────────────────────────


def test_readme_excerpt_reads_readme_md(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Widget\n\nA thing.\n")
    rel, text = repo_readme_excerpt(tmp_path)
    assert rel == "README.md"
    assert "# Widget" in text and "A thing." in text


def test_readme_excerpt_missing_returns_empty(tmp_path: Path):
    assert repo_readme_excerpt(tmp_path) == ("", "")


def test_readme_excerpt_priority_md_before_rst(tmp_path: Path):
    (tmp_path / "README.rst").write_text("rst readme")
    (tmp_path / "README.md").write_text("md readme")
    rel, text = repo_readme_excerpt(tmp_path)
    assert rel == "README.md"
    assert text == "md readme"


def test_readme_excerpt_falls_back_to_docs_readme(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("docs readme")
    rel, text = repo_readme_excerpt(tmp_path)
    assert rel == "docs/README.md"


def test_readme_excerpt_truncates_with_marker(tmp_path: Path):
    body = "\n".join(f"line {i}" for i in range(2000))
    (tmp_path / "README.md").write_text(body)
    _, text = repo_readme_excerpt(tmp_path, max_chars=200)
    assert len(text) < 400
    assert "README truncated" in text


# ── foreign_context_block ───────────────────────────────────


def test_block_includes_repo_readme_and_gate(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Acme Widget\n\nUse the gizmo API.\n")
    block = foreign_context_block(
        tmp_path, "acme/widget", "pytest -q",
        "tests/test_x.py::test_y FAILED\nE   AssertionError",
    )
    assert "acme/widget" in block
    assert "README.md" in block and "gizmo API" in block
    assert "pytest -q" in block
    assert "AssertionError" in block
    assert "currently RED" in block


def test_block_without_readme_still_has_gate(tmp_path: Path):
    block = foreign_context_block(tmp_path, "acme/widget", "npm test", "1 failing")
    assert "no README found" in block
    assert "npm test" in block
    assert "1 failing" in block


def test_block_trims_long_gate_output(tmp_path: Path):
    big = "\n".join(f"err {i}" for i in range(500))
    block = foreign_context_block(
        tmp_path, "acme/widget", "pytest", big, gate_tail_lines=20)
    # Only the tail is kept; the earliest lines are dropped with a marker.
    assert "err 499" in block
    assert "err 0\n" not in block
    assert "trimmed" in block


def test_block_handles_empty_gate_output(tmp_path: Path):
    block = foreign_context_block(tmp_path, "acme/widget", "pytest", "")
    assert "no output captured" in block


def test_block_is_chimera_free(tmp_path: Path):
    (tmp_path / "README.md").write_text("a foreign project")
    block = foreign_context_block(tmp_path, "acme/widget", "pytest", "fail")
    # The whole point of B.3: nothing chimera-internal leaks into foreign context.
    assert "chimera" not in block.lower()
