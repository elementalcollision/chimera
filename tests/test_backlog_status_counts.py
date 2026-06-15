"""Tests for count_by_status in chimera.core.backlog."""

from __future__ import annotations

import tempfile
from pathlib import Path

from chimera.core.backlog import count_by_status


def _make_backlog_dir(spec_contents: dict[str, str]) -> Path:
    """Create a temp mind dir with a backlog/ subdir of given spec files.

    ``spec_contents`` maps filename → YAML frontmatter body.
    """
    d = Path(tempfile.mkdtemp(prefix="test_backlog_"))
    backlog = d / "backlog"
    backlog.mkdir()
    for fname, content in spec_contents.items():
        (backlog / fname).write_text(content, encoding="utf-8")
    return d


def test_count_by_status_mixed():
    """One ready, one done, one invalid → {"ready":1,"done":1,"invalid":1}."""
    specs = {
        "01-ready.md": "---\ngoal: ready task\nfiles: tests/test_x.py\n---\nbody",
        "02-done.md": "---\ngoal: done task\nfiles: tests/test_x.py\ndone: true\n---\nbody",
        "03-invalid.md": "no frontmatter here",
    }
    d = _make_backlog_dir(specs)
    assert count_by_status(d) == {"ready": 1, "done": 1, "invalid": 1}


def test_count_by_status_empty():
    """Empty backlog → {"ready":0,"done":0,"invalid":0}."""
    d = Path(tempfile.mkdtemp(prefix="test_backlog_empty_"))
    (d / "backlog").mkdir()
    assert count_by_status(d) == {"ready": 0, "done": 0, "invalid": 0}
