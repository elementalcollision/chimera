"""B1: real-repo verification gate (ruff + pytest), the production primitive."""

from __future__ import annotations

import sys

from chimera.core.repo_verify import (
    CheckResult,
    VerificationReport,
    default_checks,
    run_check,
    verify_change,
)


# ── orchestration (injected trivial checks → deterministic) ─────────


def test_all_pass_is_ok(tmp_path):
    rep = verify_change(tmp_path, checks=[("a", ["true"]), ("b", ["true"])])
    assert rep.ok
    assert [c.name for c in rep.checks] == ["a", "b"]
    assert rep.summary().startswith("PASS")
    assert rep.failed == []


def test_one_fail_is_not_ok(tmp_path):
    rep = verify_change(tmp_path, checks=[("a", ["true"]), ("b", ["false"])])
    assert rep.ok is False
    assert [c.name for c in rep.failed] == ["b"]
    assert rep.summary().startswith("FAIL")


def test_empty_checks_is_not_ok(tmp_path):
    assert verify_change(tmp_path, checks=[]).ok is False


def test_failure_detail_captures_output(tmp_path):
    # A command that prints to stderr and exits non-zero.
    r = run_check(
        "boom",
        [sys.executable, "-c", "import sys; sys.stderr.write('the real error'); sys.exit(1)"],
        tmp_path, timeout=30,
    )
    assert r.passed is False
    assert r.returncode == 1
    assert "the real error" in r.detail


def test_missing_program_is_failed_not_raised(tmp_path):
    r = run_check("nope", ["this-program-does-not-exist-xyz"], tmp_path, timeout=30)
    assert r.passed is False
    assert "did not run" in r.detail


# ── default_checks shape ────────────────────────────────────────────


def test_default_checks_are_ruff_then_pytest():
    checks = default_checks()
    names = [n for n, _ in checks]
    assert names == ["ruff", "pytest"]
    ruff_argv = dict(checks)["ruff"]
    pytest_argv = dict(checks)["pytest"]
    assert ruff_argv[:4] == ["uv", "run", "ruff", "check"]
    assert "pytest" in pytest_argv


def test_default_checks_narrow_to_targets():
    checks = dict(default_checks(test_target="tests/test_x.py", ruff_paths=["chimera/x.py"]))
    assert checks["ruff"][-1] == "chimera/x.py"
    assert checks["pytest"][-1] == "tests/test_x.py"


def test_default_checks_test_target_carries_pytest_flags():
    """ADR 0182: a tokenised test_target can carry pytest flags so a
    warning-only fix is gate-visible (e.g. -W error makes a deprecation a
    hard failure). A bare path still tokenises to itself."""
    checks = dict(default_checks(test_target="-W error::DeprecationWarning tests/test_x.py"))
    assert checks["pytest"][-3:] == ["-W", "error::DeprecationWarning", "tests/test_x.py"]
    # Bare path unchanged.
    bare = dict(default_checks(test_target="tests/test_x.py::test_y"))
    assert bare["pytest"][-1] == "tests/test_x.py::test_y"


# ── report ──────────────────────────────────────────────────────────


def test_report_ok_and_failed_properties():
    rep = VerificationReport([
        CheckResult("a", True), CheckResult("b", False, "boom", 1),
    ])
    assert rep.ok is False
    assert rep.failed[0].name == "b"


# ── integration: real ruff against a known-clean file ───────────────


def test_real_ruff_passes_on_clean_file():
    """Exercises the actual `uv run ruff check` against a file we keep clean —
    proves the default pipeline runs the project's real linter."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    rep = verify_change(
        repo,
        checks=[("ruff", ["uv", "run", "ruff", "check", "chimera/core/repo_verify.py"])],
        timeout=120,
    )
    assert rep.ok, rep.checks[0].detail
