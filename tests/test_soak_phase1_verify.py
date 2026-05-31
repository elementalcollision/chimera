"""B1 Chip 3: the verify-based phase-1 sentinel `soak_phase1_verify_green`.

Unlike the marker-based phase-1 sentinel (v43 fan-out), the real-task soak's
phase 1 has NO `.md` ready-marker — the deliverable is a modification to an
existing source file. The exit is purely empirical: a real, in-scope working-
tree change AND a green gate. These tests pin that AND across a tmp git repo:

  1. the working tree differs from base (a change happened), AND
  2. every changed path is in the allowlist (mind/* auto-allowed), AND
  3. the gate command exits 0.

The gate stands in here as `true` (green) / `false` (red) — in production it
is `uv run chimera verify ...`.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOAK_LIB = REPO_ROOT / "scripts" / "soak_lib.sh"


def _git(wt: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=wt, check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    """A tiny git repo with one committed source file on branch `base`."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q", "-b", "base")
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "t")
    (wt / "chimera").mkdir()
    (wt / "tests").mkdir()
    (wt / "chimera" / "foo.py").write_text("x = 1\n")
    (wt / "tests" / "test_foo.py").write_text("def test(): assert True\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "base")
    return wt


def _call(wt: Path, allowed: str, gate: str, base: str = "base") -> int:
    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        soak_phase1_verify_green "{wt}" "{allowed}" "{gate}" "{base}"
        echo "RC=$?"
    """)
    out = subprocess.run(["bash", "-c", script],  # noqa: S602,S603
                         capture_output=True, text=True, timeout=30).stdout
    assert "RC=" in out, out
    return int(out.split("RC=")[1].split()[0])


_ALLOWED = "chimera/foo.py tests/test_foo.py"


def test_in_scope_change_green_gate_is_landed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "chimera" / "foo.py").write_text("x = 2  # fixed\n")
    assert _call(wt, _ALLOWED, "true") == 0


def test_no_change_is_not_landed(tmp_path):
    wt = _repo(tmp_path)
    # clean working tree → no diff vs base
    assert _call(wt, _ALLOWED, "true") == 1


def test_in_scope_change_but_red_gate_is_not_landed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "chimera" / "foo.py").write_text("x = 2\n")
    assert _call(wt, _ALLOWED, "false") == 1


def test_out_of_scope_change_is_not_landed(tmp_path):
    wt = _repo(tmp_path)
    # touch a tracked file NOT in the allowlist
    (wt / "tests" / "test_foo.py").write_text("def test(): assert True  # x\n")
    assert _call(wt, "chimera/foo.py", "true") == 1


def test_mind_journal_change_is_auto_allowed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "mind").mkdir()
    (wt / "mind" / "CHRONICLE.md").write_text("note\n")
    _git(wt, "add", "-A")  # track it so it shows in diff
    (wt / "chimera" / "foo.py").write_text("x = 3\n")
    # in-scope code change + a mind/ change → still landed
    assert _call(wt, "chimera/foo.py", "true") == 0


def test_bad_args_returns_two(tmp_path):
    wt = _repo(tmp_path)
    assert _call(wt, "", "true") == 2
