"""`chimera mind count` CLI verb — thin wrapper over chimera.mindcount.

Smoke-tests the v40′ landing: the verb resolves mind_dir from
LoopConfig.from_env() and prints format_mind_counts() output, exit 0.
The per-entry counting contract itself is covered by test_mindcount.py.
"""

from __future__ import annotations

import io
import contextlib
from pathlib import Path

from chimera import cli


def _run(monkeypatch, tmp_path: Path) -> tuple[int, str]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["mind", "count"])
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 2
    return rc, buf.getvalue()


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n")


def test_mind_count_verb_prints_per_entry(monkeypatch, tmp_path):
    m = tmp_path / "mind"
    _touch(m / "alpha" / "a1.txt")
    _touch(m / "alpha" / "a2.txt")
    _touch(m / "notes.txt")
    _touch(m / ".hidden")
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    assert out == "alpha: 2\nnotes.txt: 1\n"
