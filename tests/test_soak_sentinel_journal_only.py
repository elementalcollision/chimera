"""2026-06-12 campaign, Finding 2: the mind/* journal auto-allow is
permissive, NOT sufficient.

Both cells (realtask-2026-06-12-1303 / -1315) exited phase 1 via
`soft_sentinel_verify_green` with ZERO allowlist files changed — the
journal diff alone satisfied the "real in-scope diff" predicate. The
phase-2 sentinel had the identical hole: a journal-only [agent] commit
(exactly what the ADR 0148 autocommit produced, Finding 3) satisfied it.

These tests pin soak_lib v7: at least one changed path must come from the
allowlist; mind/* paths may ride along but cannot carry the exit alone.
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
    """A tiny git repo on branch `base` with one allowlisted source file
    and a tracked mind/ journal."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q", "-b", "base")
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "t")
    (wt / "chimera").mkdir()
    (wt / "chimera" / "foo.py").write_text("x = 1\n")
    (wt / "mind").mkdir()
    (wt / "mind" / "CHRONICLE.md").write_text("seed\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "base")
    return wt


def _sentinel(wt: Path, fn: str, allowed: str = "chimera/foo.py") -> int:
    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        {fn} "{wt}" "{allowed}" "true" "base"
        echo "RC=$?"
    """)
    out = subprocess.run(["bash", "-c", script],  # noqa: S602,S603
                         capture_output=True, text=True, timeout=30).stdout
    assert "RC=" in out, out
    return int(out.split("RC=")[1].split()[0])


# ── phase 1: soak_phase1_verify_green (the Finding 2 exit) ──


def test_phase1_journal_only_diff_is_not_landed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "mind" / "CHRONICLE.md").write_text("journal grew\n")
    (wt / "mind" / "research").mkdir()
    (wt / "mind" / "research" / "design.md").write_text("design note\n")
    _git(wt, "add", "-A")  # track so the diff vs base sees them
    assert _sentinel(wt, "soak_phase1_verify_green") == 1


def test_phase1_journal_plus_allowlist_change_is_landed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "mind" / "CHRONICLE.md").write_text("journal grew\n")
    (wt / "chimera" / "foo.py").write_text("x = 2  # fixed\n")
    assert _sentinel(wt, "soak_phase1_verify_green") == 0


def test_phase1_allowlist_only_change_is_landed(tmp_path):
    wt = _repo(tmp_path)
    (wt / "chimera" / "foo.py").write_text("x = 2  # fixed\n")
    assert _sentinel(wt, "soak_phase1_verify_green") == 0


# ── phase 2: soak_phase2_deliverable_landed (same hole, commit-shaped) ──


def test_phase2_journal_only_agent_commit_is_not_landed(tmp_path):
    """The exact shape the ADR 0148 autocommit produced in both cells:
    an [agent] commit carrying only mind/ artifacts."""
    wt = _repo(tmp_path)
    _git(wt, "checkout", "-q", "-b", "soak")
    (wt / "mind" / "CHRONICLE.md").write_text("journal grew\n")
    _git(wt, "add", "mind")
    _git(wt, "commit", "-q", "-m", "[agent] fix foo — harness-committed")
    assert _sentinel(wt, "soak_phase2_deliverable_landed") == 1


def test_phase2_agent_commit_with_deliverable_is_landed(tmp_path):
    wt = _repo(tmp_path)
    _git(wt, "checkout", "-q", "-b", "soak")
    (wt / "chimera" / "foo.py").write_text("x = 2  # fixed\n")
    (wt / "mind" / "CHRONICLE.md").write_text("journal grew\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "[agent] fix foo")
    assert _sentinel(wt, "soak_phase2_deliverable_landed") == 0
