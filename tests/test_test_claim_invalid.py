"""v4.113 (ADR 0113): runtime test-claim validity gate.

Soak v16 (PR #5) surfaced this gap: the agent claimed
``uv run pytest tests/test_doctor.py`` had succeeded, but the file's
tests raised ``NameError: name 're' is not defined`` at runtime —
``chimera/core/doctor.py`` used ``re.compile(...)`` without importing
``re``. None of the existing 14 detectors caught the gap because they
verify structural correctness (parse, presence, paths) but never run
the code.

This module tests :func:`chimera.core.act.check_test_claim_valid` and
verifies the detector is wired into the escalation / trust / remediation
pipeline.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from chimera.core.act import check_test_claim_valid
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _test_claim_invalid_hint,
    derive_remediation_hint,
)
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


def _make_pkg(root: Path) -> Path:
    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    return tests_dir


# ── check_test_claim_valid ──────────────────────────────────────────


def test_no_pytest_mention_is_silent(tmp_path: Path) -> None:
    """If task text doesn't claim a pytest run, detector returns []."""
    task = "Refactor the doctor module to add an orphan-worktrees check."
    assert check_test_claim_valid(task, [], tmp_path) == []


def test_passing_tests_do_not_fire(tmp_path: Path) -> None:
    tests_dir = _make_pkg(tmp_path)
    (tests_dir / "test_ok.py").write_text(
        "def test_passes():\n    assert 1 + 1 == 2\n"
    )
    task = "Ran `uv run pytest tests/test_ok.py` — all green."
    failures = check_test_claim_valid(task, [], tmp_path)
    assert failures == []


def test_v16_nameerror_regression_fires(tmp_path: Path) -> None:
    """The exact failure shape from soak v16: task claims a pytest run
    succeeded, but the file under test raises ``NameError: name 're'``
    at runtime. py_compile passes; only execution catches it.
    """
    tests_dir = _make_pkg(tmp_path)
    # Implementation has the v16 defect — uses re.compile without
    # importing re. py_compile passes; runtime NameError.
    (tmp_path / "doctor.py").write_text(
        "def check_orphans():\n"
        "    pattern = re.compile(r'foo')\n"
        "    return pattern\n"
    )
    (tests_dir / "test_doctor.py").write_text(
        "from doctor import check_orphans\n"
        "def test_check_orphans():\n"
        "    assert check_orphans() is not None\n"
    )
    task = textwrap.dedent("""\
        Implement orphan-worktrees check. Verify with
        `uv run pytest tests/test_doctor.py` — confirmed 6 tests
        passing.
    """)
    failures = check_test_claim_valid(task, [], tmp_path)
    assert failures, f"expected NameError to be caught, got {failures!r}"
    assert any("tests/test_doctor.py" in p for p in failures)


def test_python_m_pytest_form_also_recognised(tmp_path: Path) -> None:
    tests_dir = _make_pkg(tmp_path)
    (tests_dir / "test_x.py").write_text(
        "def test_fail():\n    assert False\n"
    )
    task = "Verified with `python -m pytest tests/test_x.py` — passed."
    failures = check_test_claim_valid(task, [], tmp_path)
    assert failures
    assert any("tests/test_x.py" in p for p in failures)


def test_nonexistent_test_file_is_silent(tmp_path: Path) -> None:
    """If the claimed file doesn't exist, defer to artifact_missing."""
    _make_pkg(tmp_path)
    task = "Verified `uv run pytest tests/test_ghost.py` — green."
    assert check_test_claim_valid(task, [], tmp_path) == []


def test_malformed_pytest_command_returns_empty(tmp_path: Path) -> None:
    """Charter: never raise on weird input."""
    task = "Ran pytest. It worked."  # no concrete path
    assert check_test_claim_valid(task, [], tmp_path) == []


def test_pytest_collection_error_returns_ok(tmp_path: Path) -> None:
    """v4.113 / PR #6 review (Class A + B): a collection error
    (ImportError, missing module, syntax error in the test module) is
    environmental — pytest exits with code 2, not 1. The detector must
    NOT fire on those: synthetic-fixture worktrees and sandbox runs
    routinely produce collection errors that have nothing to do with
    the agent's claim being a lie.
    """
    tests_dir = _make_pkg(tmp_path)
    # Test file that import-errors at collection time (module doesn't
    # exist in the synthetic env's path). Pytest exits 2.
    (tests_dir / "test_collection_err.py").write_text(
        "import this_module_does_not_exist_anywhere\n"
        "def test_x():\n    assert True\n"
    )
    task = "Verified `uv run pytest tests/test_collection_err.py` — green."
    # Collection errors are NOT claim violations — return [].
    assert check_test_claim_valid(task, [], tmp_path) == []


def test_pytest_no_tests_collected_returns_ok(tmp_path: Path) -> None:
    """A test file with no test_* functions (pytest exit 5) is a
    placeholder, not a failure. Don't fire."""
    tests_dir = _make_pkg(tmp_path)
    (tests_dir / "test_placeholder.py").write_text(
        "def helper(): pass\n"  # no test_* function
    )
    task = "Verified `uv run pytest tests/test_placeholder.py` — green."
    assert check_test_claim_valid(task, [], tmp_path) == []


def test_passing_tests_in_isolated_tmp_path_do_not_fire(tmp_path: Path) -> None:
    """Lock down the isolated-tmp_path case: a self-contained passing
    test under tmp_path/tests/ must not be misreported as a failure
    regardless of the env pytest is configured against (PR #6 review
    Class B).
    """
    tests_dir = _make_pkg(tmp_path)
    (tests_dir / "test_isolated.py").write_text(
        "def test_one():\n    assert 1 == 1\n"
        "def test_two():\n    assert 'a' + 'b' == 'ab'\n"
    )
    task = "Ran `uv run pytest tests/test_isolated.py` — 2 passed."
    assert check_test_claim_valid(task, [], tmp_path) == []


# ── escalation / trust / remediation wiring ─────────────────────────


def test_test_claim_invalid_is_escalating_finish_reason() -> None:
    assert "test_claim_invalid" in ESCALATING_FINISH_REASONS


def test_test_claim_invalid_trust_delta_is_one() -> None:
    assert FINISH_REASON_TRUST_DELTAS["test_claim_invalid"] == 1


def test_hint_without_detail_is_generic() -> None:
    hint = _test_claim_invalid_hint("ran `uv run pytest tests/x.py`")
    assert "pytest" in hint.lower()
    assert "fix" in hint.lower()


def test_hint_with_detail_names_failure() -> None:
    hint = _test_claim_invalid_hint(
        "ran `uv run pytest tests/test_doctor.py`",
        test_claim_failures=[(
            "tests/test_doctor.py",
            "NameError: name 're' is not defined",
        )],
    )
    assert "tests/test_doctor.py" in hint
    assert "NameError" in hint


def test_derive_remediation_hint_handles_test_claim_invalid() -> None:
    hint = derive_remediation_hint("some task", "test_claim_invalid")
    assert hint is not None
    assert "pytest" in hint.lower() or "test" in hint.lower()
