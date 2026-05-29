"""Pre-written contract test for the v40′ build-capability probe.

Charter: mind/research/v40prime-mindcount-design.md. This file is the
operator-authored gate, committed to main in a FAILING state before the
soak. Chimera's task is to create chimera/mindcount.py with a
``format_mind_counts`` function that makes these tests pass — WITHOUT
touching chimera/cli.py (the v40 capstone's self-denial confound is
removed by targeting an isolated module).

Strict-mode probe: the design note names only this file's path; the
agent discovers the contract by reading these assertions. They ARE the
spec — keep them exact.

Contract for ``chimera.mindcount.format_mind_counts(mind_dir) -> str``:
  - Returns one line per top-level entry under mind_dir, ``"<name>: <count>\\n"``.
  - A subdirectory's count is the recursive file count beneath it (any depth).
  - A top-level file is ``1``.
  - Lines sorted alphabetically by name.
  - Hidden entries (names starting with ``.``) skipped — files and dirs.
  - Pure: returns the string, no print / network / writes.

Harness note: pre-implementation, ``chimera.mindcount`` does not exist.
``_fmt`` imports it INSIDE the call and converts a missing module/function
to a clean assertion failure, so the suite shows N *failed*, never a
collection *error*. CI-green: the whole module is skipped unless
CHIMERA_V40_GATE is set (lands failing only under the gate env).
"""

from __future__ import annotations

from pathlib import Path

from chimera.mindcount import format_mind_counts

# v40′ gate cleared (PR #145 soak, 2026-05-29): chimera/mindcount.py is now
# on main, so these contract tests run unconditionally in CI. The
# CHIMERA_V40_GATE skipif that let this file land FAILING before the build
# soak has been removed now that the implementation exists.


def _fmt(mind_dir: Path) -> str:
    return format_mind_counts(mind_dir)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")


def test_basic_exact_output(tmp_path):
    m = tmp_path / "mind"
    _touch(m / "alpha" / "a1.txt")
    _touch(m / "alpha" / "a2.txt")
    _touch(m / "beta" / "sub" / "b1.txt")
    _touch(m / "gamma" / "g1.txt")
    _touch(m / "gamma" / "g2.txt")
    _touch(m / "gamma" / "g3.txt")
    _touch(m / "notes.txt")
    assert _fmt(m) == "alpha: 2\nbeta: 1\ngamma: 3\nnotes.txt: 1\n"


def test_recursive_any_depth(tmp_path):
    m = tmp_path / "mind"
    _touch(m / "deep" / "a" / "b" / "c" / "f1.txt")
    _touch(m / "deep" / "a" / "f2.txt")
    _touch(m / "deep" / "f3.txt")
    assert _fmt(m) == "deep: 3\n"


def test_toplevel_file_is_one(tmp_path):
    m = tmp_path / "mind"
    _touch(m / "solo.md")
    assert _fmt(m) == "solo.md: 1\n"


def test_sorted_alphabetically(tmp_path):
    m = tmp_path / "mind"
    _touch(m / "zeta.txt")
    _touch(m / "mid" / "m1.txt")
    _touch(m / "able.txt")
    assert _fmt(m) == "able.txt: 1\nmid: 1\nzeta.txt: 1\n"


def test_skips_hidden(tmp_path):
    m = tmp_path / "mind"
    _touch(m / "visible.txt")
    _touch(m / ".hidden_file")
    _touch(m / ".hidden_dir" / "secret.txt")
    assert _fmt(m) == "visible.txt: 1\n"
