"""H1 (v42 fix): commit_bypasses_index — close the scope-check evasion.

The pre-commit scope check (ADR 0146) inspects `git diff --cached`. A
`git commit <pathspec>` / `-a` / `--amend` commits files outside that
staged snapshot, evading the allowlist (v42 attempt #1 landed an
off-charter tests/ file this way). commit_bypasses_index flags those
forms so the shell gate can refuse them and force the staged flow.
"""

from __future__ import annotations

import pytest

from chimera.core.scope_check import commit_bypasses_index


# ── forms that BYPASS the index → must return a reason ───────────

@pytest.mark.parametrize("argv", [
    ["git", "commit", "tests/test_x.py"],                 # bare pathspec
    ["git", "commit", "-m", "msg", "chimera/x.py"],        # pathspec after -m value
    ["git", "commit", "-a", "-m", "msg"],                  # -a
    ["git", "commit", "-am", "msg"],                       # combined -am
    ["git", "commit", "--all", "-m", "msg"],               # --all
    ["git", "commit", "--amend", "-m", "msg"],             # --amend
    ["git", "commit", "-m", "msg", "--", "a.py"],          # pathspec after --
    ["git", "commit", "--only", "a.py"],                   # --only
    ["git", "commit", "-i", "a.py"],                       # --include
    ["git", "commit", "--no-verify", "-m", "msg"],         # --no-verify
])
def test_bypassing_forms_flagged(argv):
    assert commit_bypasses_index(argv) is not None


# ── auditable staged forms → must return None ────────────────────

@pytest.mark.parametrize("argv", [
    ["git", "commit", "-m", "msg"],                        # bare staged commit
    ["git", "commit", "-m", "a message with spaces"],      # message value not a pathspec
    ["git", "commit", "--message", "msg"],                 # long message flag
    ["git", "commit", "-F", "/tmp/msg.txt"],               # message-from-file value
    ["git", "commit", "--cleanup", "strip", "-m", "msg"],  # cleanup value
    ["git", "commit"],                                     # opens editor; staged only
    ["git", "status"],                                     # not a commit
    ["git", "add", "x.py"],                                # not a commit
    ["uv", "run", "pytest"],                               # not git
])
def test_staged_forms_pass(argv):
    assert commit_bypasses_index(argv) is None


def test_message_value_that_looks_like_path_is_not_pathspec():
    # `-m tests/foo` — the token after -m is the message, not a pathspec.
    assert commit_bypasses_index(["git", "commit", "-m", "tests/foo"]) is None
