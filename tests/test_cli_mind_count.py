"""Pre-written contract test for the `chimera mind count` CLI verb.

This file is the **v40 build-capability probe** (charter:
``mind/research/v40-build-mind-count-design.md``). It is authored by the
operator BEFORE the soak and committed to main in a deliberately FAILING
state — Chimera has not yet written the implementation. The soak's
primary gate is: code Chimera authors makes these tests pass, byte-for-
byte, without editing this file.

Strict-mode probe: the design note names this file's path only; it does
NOT embed the contract prose. The agent discovers the contract by
reading this test during ACT. Therefore the assertions below ARE the
spec. Keep them exact.

Contract for ``chimera mind count`` (read-only ``os.walk`` over mind/):
  - Exits 0.
  - Prints one line per top-level entry under ``mind/`` of the form
    ``<name>: <integer>``.
  - A subdirectory's integer is the recursive count of files beneath it
    (any depth).
  - A top-level file reports ``1``.
  - Output is sorted alphabetically by name.
  - Hidden entries (names starting with ``.``) are skipped — both
    hidden top-level files and hidden directories.

Harness note: pre-implementation, argparse raises ``SystemExit(2)`` on
the unknown ``mind`` command. ``_run`` catches that and returns it as a
code, so each assertion FAILS cleanly rather than ERRORing — the
operator's green-run acceptance step expects exactly 5 *failed*, 0
errors.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from chimera import cli

# This file lands on main FAILING (pre-implementation). To keep the
# main CI suite green, it is skipped unless the v40 gate env is set.
# The operator green-run, the soak runner, and the post-soak primary
# gate all export CHIMERA_V40_GATE=1, so:
#   - default CI               → 5 skipped  (suite stays green)
#   - CHIMERA_V40_GATE=1, pre   → 5 failed   (gate NOT cleared)
#   - CHIMERA_V40_GATE=1, post  → 5 passed   (gate cleared)
# The soak supervisor MUST export this var into the agent's env, or the
# agent's own `pytest` checks would see "5 skipped" and mistake an
# unimplemented verb for a pass.
pytestmark = pytest.mark.skipif(
    not os.environ.get("CHIMERA_V40_GATE"),
    reason="v40 build-capability gate; run with CHIMERA_V40_GATE=1",
)


def _run(monkeypatch, tmp_path: Path) -> tuple[int, str]:
    """Invoke ``chimera mind count`` from ``tmp_path`` and capture stdout.

    Returns ``(exit_code, stdout)``. A ``SystemExit`` (argparse on the
    not-yet-implemented subcommand, or an explicit nonzero exit) is
    normalized to an int code so tests fail on assertion, never error.
    """
    monkeypatch.chdir(tmp_path)
    # Don't let an ambient CHIMERA_MIND_DIR redirect the walk away from
    # the fixture's ./mind.
    monkeypatch.delenv("CHIMERA_MIND_DIR", raising=False)
    import io
    import contextlib

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["mind", "count"])
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 2
    return rc, buf.getvalue()


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")


def _basic_mind(tmp_path: Path) -> None:
    """A controlled mind/ layout with known counts.

    mind/
      alpha/  a1.txt a2.txt              -> 2
      beta/   sub/b1.txt                 -> 1  (recursive, nested one deep)
      gamma/  g1.txt g2.txt g3.txt       -> 3
      notes.txt                          -> 1  (top-level file)
    """
    mind = tmp_path / "mind"
    _touch(mind / "alpha" / "a1.txt")
    _touch(mind / "alpha" / "a2.txt")
    _touch(mind / "beta" / "sub" / "b1.txt")
    _touch(mind / "gamma" / "g1.txt")
    _touch(mind / "gamma" / "g2.txt")
    _touch(mind / "gamma" / "g3.txt")
    _touch(mind / "notes.txt")


# ── 1. Exit 0 + exact basic output ───────────────────────────

def test_mind_count_exit_zero_and_exact_lines(monkeypatch, tmp_path):
    _basic_mind(tmp_path)
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    assert out == "alpha: 2\nbeta: 1\ngamma: 3\nnotes.txt: 1\n"


# ── 2. Subdirectory counts are recursive (any depth) ─────────

def test_mind_count_subdir_recursive_any_depth(monkeypatch, tmp_path):
    mind = tmp_path / "mind"
    _touch(mind / "deep" / "a" / "b" / "c" / "f1.txt")
    _touch(mind / "deep" / "a" / "f2.txt")
    _touch(mind / "deep" / "f3.txt")
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    assert out == "deep: 3\n"


# ── 3. A top-level file reports 1 ────────────────────────────

def test_mind_count_toplevel_file_is_one(monkeypatch, tmp_path):
    mind = tmp_path / "mind"
    _touch(mind / "solo.md")
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    assert out == "solo.md: 1\n"


# ── 4. Output is sorted alphabetically by name ───────────────

def test_mind_count_sorted_alphabetically(monkeypatch, tmp_path):
    mind = tmp_path / "mind"
    # Create out of alphabetical order; output must still be sorted.
    _touch(mind / "zeta.txt")
    _touch(mind / "mid" / "m1.txt")
    _touch(mind / "able.txt")
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    assert out == "able.txt: 1\nmid: 1\nzeta.txt: 1\n"


# ── 5. Hidden entries (files and dirs) are skipped ───────────

def test_mind_count_skips_hidden(monkeypatch, tmp_path):
    mind = tmp_path / "mind"
    _touch(mind / "visible.txt")
    _touch(mind / ".hidden_file")
    _touch(mind / ".hidden_dir" / "secret.txt")
    rc, out = _run(monkeypatch, tmp_path)
    assert rc == 0
    # Only the visible top-level file appears.
    assert out == "visible.txt: 1\n"
