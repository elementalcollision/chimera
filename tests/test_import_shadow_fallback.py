"""v43 R2 coverage follow-up: the import-shadow gate must fire from a
WRITTEN .py file, not only when ``write_targets`` is populated.

PR #163 gave the postmortem-honesty gate a ``git status`` fallback (the v43
soak ran every write-target gate dormant because ``write_targets`` was empty
all run — the agent wrote via the ``shell`` tool, excluded from
``_WRITING_TOOL_NAMES``). This extends the SAME fallback to
``check_import_shadowing`` so the UnboundLocalError-class shadow that bricked
v40 #2/#4 is caught regardless of which tool wrote the file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.act import (
    _gate_targets,
    _import_shadow_scan_root,
    check_import_shadowing,
)

# A module that shadows a module-level import inside a function — the exact
# UnboundLocalError class the gate exists to catch.
_SHADOW_SRC = (
    "import os\n\n\n"
    "def main():\n"
    "    print(os.getcwd())\n"
    "    import os  # function-local shadow of the module-level os\n"
    "    return os.path.join('a', 'b')\n"
)
_CLEAN_SRC = (
    "import os\n\n\n"
    "def main():\n"
    "    return os.getcwd()\n"
)


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return tmp_path


def _write(root: Path, rel: str, src: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)
    return p


# ── the fallback: fires from a written-but-uncaptured .py ─────────

def test_fallback_catches_shadow_when_write_targets_empty(tmp_path):
    root = _git_repo(tmp_path)
    _write(root, "chimera/mod.py", _SHADOW_SRC)
    # write_targets empty (the v43 condition) — found via git status.
    failures = check_import_shadowing([], worktree_root=root)
    assert len(failures) == 1
    path, msg = failures[0]
    assert path.endswith("chimera/mod.py") and "shadows" in msg and "os" in msg


def test_fallback_clean_file_no_false_positive(tmp_path):
    root = _git_repo(tmp_path)
    _write(root, "chimera/mod.py", _CLEAN_SRC)
    assert check_import_shadowing([], worktree_root=root) == []


def test_legacy_no_worktree_is_dormant_on_empty_targets(tmp_path):
    # worktree_root=None → no fallback; empty write_targets → nothing to
    # inspect (the pre-fix behavior, kept for hermetic unit tests).
    root = _git_repo(tmp_path)
    _write(root, "chimera/mod.py", _SHADOW_SRC)
    assert check_import_shadowing([], worktree_root=None) == []


def test_write_targets_still_work_without_fallback(tmp_path):
    # The in-loop signal path is unchanged: an explicit write_target is
    # inspected even with no worktree.
    p = _write(tmp_path, "mod.py", _SHADOW_SRC)
    failures = check_import_shadowing([str(p)])
    assert len(failures) == 1 and "shadows" in failures[0][1]


def test_gate_targets_unions_and_dedupes_py(tmp_path):
    root = _git_repo(tmp_path)
    p = _write(root, "chimera/mod.py", _SHADOW_SRC)
    # Pass the same file as a write_target AND let git find it → one entry.
    targets = _gate_targets([str(p)], root, ".py")
    resolved = {str(Path(t).resolve()) for t in targets}
    assert resolved == {str(p.resolve())}


# ── v44/#169: the cwd git-scan is SOAK-SCOPED ──────────────────────
#
# The #164 fallback scanned Path.cwd() UNCONDITIONALLY at the ACT call
# site. Off-soak that fired on a developer's uncommitted .py during a real
# `chimera run` and — because unit tests run in the repo worktree — let a
# DIRTY worktree (e.g. an in-progress shadowed .py) pollute unrelated ACT
# tests. These tests pin the gate the call site uses to pick its
# worktree_root: None off-soak, Path.cwd() on-soak.

def test_scan_root_is_none_outside_soak(monkeypatch):
    # No CHIMERA_SOAK_RUN_ID → the call site passes worktree_root=None, so
    # the cwd git-scan never runs and a dirty repo cannot pollute.
    monkeypatch.delenv("CHIMERA_SOAK_RUN_ID", raising=False)
    assert _import_shadow_scan_root() is None


def test_scan_root_is_cwd_inside_soak(monkeypatch):
    monkeypatch.setenv("CHIMERA_SOAK_RUN_ID", "v44-test")
    assert _import_shadow_scan_root() == Path.cwd()


def test_dirty_worktree_does_not_pollute_off_soak(tmp_path, monkeypatch):
    # The concrete pollution scenario from landing v44: a shadowed .py
    # exists on disk in cwd, write_targets is empty, and we are NOT in a
    # soak. With the call site passing _import_shadow_scan_root() (None
    # off-soak), the gate must no-op rather than scan cwd's git status.
    root = _git_repo(tmp_path)
    _write(root, "chimera/dirty.py", _SHADOW_SRC)
    monkeypatch.chdir(root)
    monkeypatch.delenv("CHIMERA_SOAK_RUN_ID", raising=False)
    assert check_import_shadowing([], worktree_root=_import_shadow_scan_root()) == []


def test_fallback_still_catches_shadow_inside_soak(tmp_path, monkeypatch):
    # Inside a soak the fallback is live again: a real shadow on disk is
    # caught via the cwd git-scan even when write_targets is empty.
    root = _git_repo(tmp_path)
    _write(root, "chimera/dirty.py", _SHADOW_SRC)
    monkeypatch.chdir(root)
    monkeypatch.setenv("CHIMERA_SOAK_RUN_ID", "v44-test")
    failures = check_import_shadowing([], worktree_root=_import_shadow_scan_root())
    assert len(failures) == 1
    path, msg = failures[0]
    assert path.endswith("chimera/dirty.py") and "shadows" in msg
