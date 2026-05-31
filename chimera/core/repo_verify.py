"""Real-repo verification — the B1 production gate.

The self-charter loop (S1+S2) builds against a PRE-WRITTEN charter test: "passes
the test we gave it." Production value (roadmap B1) is the harder thing — a
change verified against the repo's OWN checks: its real test suite, its linter,
its type/parse checks. No pre-written test for the change; the existing pipeline
IS the gate. This module is that gate: run the project's real checks over a
worktree and return a structured pass/fail with the failure detail an agent (or
operator) needs to act on.

Deterministic and injectable: the default checks are ruff + pytest, but any
check is a ``(name, argv)`` pair, so the orchestration is unit-tested with
trivial commands and the real checks are exercised by an integration test.
Charter: never raise — a check that errors is a FAILED check with its output as
the detail, not an exception.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# How much of a failing check's output to keep as actionable detail.
_DETAIL_TAIL_CHARS = 4000


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = "ok"           # failure tail (stdout+stderr), or "ok"
    returncode: int | None = None


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        if not self.checks:
            return "no checks run"
        if self.ok:
            return "PASS — " + ", ".join(f"{c.name} ✓" for c in self.checks)
        parts = [f"{c.name} {'✓' if c.passed else '✗'}" for c in self.checks]
        return "FAIL — " + ", ".join(parts)


def default_checks(
    *, test_target: str | None = None, ruff_paths: list[str] | None = None,
) -> list[tuple[str, list[str]]]:
    """The repo's real verification pipeline: ruff then pytest.

    ``test_target`` narrows pytest to the affected test(s) (cheaper than the full
    suite); ``ruff_paths`` narrows the lint to the changed files. Omit both to
    run the whole repo.
    """
    ruff = ["uv", "run", "ruff", "check", *(ruff_paths or ["."])]
    pytest = ["uv", "run", "--extra", "dev", "pytest", "-q"]
    if test_target:
        pytest.append(test_target)
    return [("ruff", ruff), ("pytest", pytest)]


def run_check(name: str, argv: list[str], cwd: Path | str, timeout: float) -> CheckResult:
    """Run one check; a non-zero exit (or error) is a FAILED check, never a raise."""
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult(name, False, f"{name} did not run: {exc}", None)
    if proc.returncode == 0:
        return CheckResult(name, True, "ok", 0)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    detail = combined[-_DETAIL_TAIL_CHARS:] if combined else f"exit {proc.returncode}"
    return CheckResult(name, False, detail, proc.returncode)


def verify_change(
    repo_root: Path | str,
    *,
    checks: list[tuple[str, list[str]]] | None = None,
    test_target: str | None = None,
    ruff_paths: list[str] | None = None,
    timeout: float = 600.0,
) -> VerificationReport:
    """Run the repo's real verification over ``repo_root`` and report structured
    results. Uses :func:`default_checks` (ruff + pytest) unless ``checks`` is
    given (used by tests and for custom pipelines)."""
    if checks is None:
        checks = default_checks(test_target=test_target, ruff_paths=ruff_paths)
    root = Path(repo_root)
    return VerificationReport(
        checks=[run_check(name, argv, root, timeout) for name, argv in checks],
    )
