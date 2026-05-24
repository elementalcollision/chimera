"""v4.115 (ADR 0115): commit-message-vs-diff drift detector.

Soak v20-relaunch surfaced this gap: an [agent] commit landed
``chimera/core/act.py`` plus a research doc; the commit message body
claimed the work included ``tests/test_ruff_claim_invalid.py``. The
tests file existed on disk and passed locally but had never been
``git add``-ed before the commit, so the cumulative branch diff did
not carry it. None of the existing detectors caught the gap because
they look at task_text or the diff in isolation — nobody compared the
commit message against the diff.

This module tests
:func:`chimera.core.act.check_commit_message_diff_drift` and verifies
the detector is wired into the escalation / trust / remediation chain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.act import (
    _extract_commit_path_claims,
    check_commit_message_diff_drift,
)
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _commit_message_diff_drift_hint,
    derive_remediation_hint,
)
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


def _git(*args: str, cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, check=True,
    )
    return res.stdout


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("base\n")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "initial", cwd=root)
    _git("checkout", "-q", "-b", "feat/x", cwd=root)


# ── _extract_commit_path_claims ─────────────────────────────────────


def test_extract_picks_up_backticked_paths() -> None:
    msg = (
        "[agent] chimera/core/act.py: add detector\n\n"
        "Also adds `tests/test_foo.py` and updates `docs/adr/0115.md`."
    )
    assert _extract_commit_path_claims(msg) == [
        "chimera/core/act.py",
        "tests/test_foo.py",
        "docs/adr/0115.md",
    ]


def test_extract_picks_up_bare_paths() -> None:
    msg = "Touches tests/test_x.py and chimera/core/y.py for the fix."
    paths = _extract_commit_path_claims(msg)
    assert "tests/test_x.py" in paths
    assert "chimera/core/y.py" in paths


def test_extract_ignores_unrooted_strings() -> None:
    # "the test file", "the README" — no rooted path, no claim.
    msg = "Adds the test file and updates the README."
    assert _extract_commit_path_claims(msg) == []


def test_extract_dedupes() -> None:
    msg = "tests/test_x.py done. Re-ran tests/test_x.py twice."
    assert _extract_commit_path_claims(msg) == ["tests/test_x.py"]


# ── check_commit_message_diff_drift ─────────────────────────────────


def test_no_agent_prefix_is_silent(tmp_path: Path) -> None:
    """Operator commits aren't autonomous-delivery contracts."""
    _init_repo(tmp_path)
    (tmp_path / "foo.txt").write_text("x\n")
    _git("add", "foo.txt", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "soak_lib: tweak something tests/test_missing.py",
        cwd=tmp_path,
    )
    assert check_commit_message_diff_drift(tmp_path) == []


def test_honest_commit_does_not_fire(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "foo.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_x(): pass\n")
    _git("add", "chimera/foo.py", "tests/test_foo.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] chimera/foo.py: add x\n\nIncludes tests/test_foo.py.",
        cwd=tmp_path,
    )
    assert check_commit_message_diff_drift(tmp_path) == []


def test_v20_relaunch_regression_fires(tmp_path: Path) -> None:
    """The exact soak-v20-relaunch shape: message claims a tests file
    that exists on disk but was never git-add'd."""
    _init_repo(tmp_path)
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "act.py").write_text("def f(): return 1\n")
    (tmp_path / "tests").mkdir()
    # Test file exists on disk — but it's NOT git add'd.
    (tmp_path / "tests" / "test_ruff_claim_invalid.py").write_text(
        "def test_x(): assert 1\n"
    )
    _git("add", "chimera/act.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] chimera/act.py: add detector\n\n"
        "Also adds tests/test_ruff_claim_invalid.py with 6 passing tests.",
        cwd=tmp_path,
    )
    drift = check_commit_message_diff_drift(tmp_path)
    assert drift == ["tests/test_ruff_claim_invalid.py"], drift


def test_returns_empty_when_message_has_no_claims(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "x.py").write_text("y = 1\n")
    _git("add", "x.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "[agent] x.py: tweak", cwd=tmp_path)
    # x.py has no rooted prefix → no claim extracted at all.
    assert check_commit_message_diff_drift(tmp_path) == []


def test_commit_only_semantics_when_base_equals_head(tmp_path: Path) -> None:
    """ADR 0126: detector must inspect HEAD's OWN diff, not the
    cumulative ``base..HEAD`` diff. With ``base_ref == head_ref`` the
    cumulative diff is empty by construction; commit-only is still
    non-empty when HEAD itself added files. Honest claims must pass.
    """
    _init_repo(tmp_path)
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "act.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_x(): pass\n")
    _git("add", "chimera/act.py", "tests/test_foo.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] chimera/act.py: add x\n\nIncludes tests/test_foo.py.",
        cwd=tmp_path,
    )
    assert check_commit_message_diff_drift(
        tmp_path, base_ref="HEAD",
    ) == []


def test_v29_fresh_fork_does_not_fire(tmp_path: Path) -> None:
    """ADR 0126 smoking gun: soak v29 created a fresh worktree from
    main; branch HEAD == main HEAD. The most-recent ``[agent]`` merge
    commit on main mentions ``tests/test_charter_file_count.py`` in its
    body. Pre-fix: ``git diff main..HEAD`` is empty, so every rooted
    path in that body looked like drift and the detector fired 5×
    across cycles 134-136, collapsing trust to T0. Post-fix:
    ``git show HEAD`` carries the file → no drift.
    """
    _init_repo(tmp_path)
    _git("checkout", "-q", "main", cwd=tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_charter_file_count.py").write_text(
        "def test_x(): pass\n",
    )
    _git("add", "tests/test_charter_file_count.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] v26 follow-up: wire charter_file_count violations\n\n"
        "Adds tests/test_charter_file_count.py with passing coverage.",
        cwd=tmp_path,
    )
    _git("checkout", "-q", "-b", "chimera-soak/v29", cwd=tmp_path)
    assert check_commit_message_diff_drift(tmp_path) == []


def test_genuine_commit_only_drift_still_fires(tmp_path: Path) -> None:
    """ADR 0126: post-fix, genuine drift is preserved. HEAD's own
    commit diff omits a path that the message claims → fires.
    """
    _init_repo(tmp_path)
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "act.py").write_text("def f(): return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_missing.py").write_text(
        "def test_x(): assert 1\n",
    )
    _git("add", "chimera/act.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] chimera/act.py: add detector\n\n"
        "Also adds tests/test_missing.py.",
        cwd=tmp_path,
    )
    assert check_commit_message_diff_drift(tmp_path) == [
        "tests/test_missing.py",
    ]


def test_subprocess_failure_returns_empty(tmp_path: Path) -> None:
    # Not a git repo → git log fails → detector returns [].
    assert check_commit_message_diff_drift(tmp_path) == []


# ── wiring ──────────────────────────────────────────────────────────


def test_finish_reason_is_escalating() -> None:
    assert "commit_message_diff_drift" in ESCALATING_FINISH_REASONS


def test_trust_delta_is_one_tier() -> None:
    assert FINISH_REASON_TRUST_DELTAS["commit_message_diff_drift"] == 1


def test_remediation_hint_with_claims_names_them() -> None:
    hint = _commit_message_diff_drift_hint(
        "task", commit_message_drift_claims=["tests/test_x.py"],
    )
    assert "tests/test_x.py" in hint
    assert "git add" in hint or "git diff" in hint


def test_remediation_hint_db_only_path_is_generic() -> None:
    hint = _commit_message_diff_drift_hint("task")
    assert "git diff" in hint
    assert "main..HEAD" in hint


def test_derive_remediation_hint_routes() -> None:
    hint = derive_remediation_hint("task", "commit_message_diff_drift")
    assert hint is not None
    assert "commit" in hint.lower()
