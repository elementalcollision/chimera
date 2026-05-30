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

from chimera.core.act import _gate_targets, check_import_shadowing

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
