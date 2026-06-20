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

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..tools.sandbox_env import sanitized_subprocess_env

#: Kill-switch values that DISABLE the ADR 0186 B.4 M1 gate sandbox.
_SANDBOX_OFF = frozenset({"0", "false", "off", "no", ""})


def _gate_subprocess_env() -> dict[str, str] | None:
    """Sanitized env for a gate subprocess (ADR 0186 B.4 M1) — secret-named vars
    stripped so an untrusted ``verify_cmd`` can't read provider keys. Returns
    ``None`` (inherit the full env) when ``CHIMERA_GATE_SANDBOX`` is off. The gate
    is ruff/pytest, which needs no secrets (CI runs it keyless), so this is the
    default for self and foreign gates alike."""
    if os.environ.get("CHIMERA_GATE_SANDBOX", "1").strip().lower() in _SANDBOX_OFF:
        return None
    return sanitized_subprocess_env()

# How much of a failing check's output to keep as actionable detail.
_DETAIL_TAIL_CHARS = 4000

# Gate-transition classes (ADR 0182 gate-visibility prerequisite).
RED_TO_GREEN = "red_to_green"      # the change moved a failing gate to green
GREEN_TO_GREEN = "green_to_green"  # gate-INVISIBLE: already green on base
STILL_RED = "still_red"            # change did not achieve green
BASE_ERROR = "base_error"          # could not evaluate the base ref


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

    ``test_target`` is **shell-tokenised** (``shlex.split``), so it may carry
    pytest flags as well as a path — e.g. ``"-W error::DeprecationWarning
    tests/test_x.py"`` makes a deprecation a hard failure, which is how a
    warning-only fix is made gate-visible (ADR 0182: the gate must be RED on
    base). A bare path tokenises to itself, so existing single-path callers
    are unchanged.
    """
    ruff = ["uv", "run", "ruff", "check", *(ruff_paths or ["."])]
    pytest = ["uv", "run", "--extra", "dev", "pytest", "-q"]
    if test_target:
        pytest.extend(shlex.split(test_target))
    return [("ruff", ruff), ("pytest", pytest)]


def run_check(name: str, argv: list[str], cwd: Path | str, timeout: float) -> CheckResult:
    """Run one check; a non-zero exit (or error) is a FAILED check, never a raise."""
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
            env=_gate_subprocess_env(),
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


@dataclass
class GateVisibilityReport:
    """Did the change actually MOVE the gate? (ADR 0182 gate-visibility.)

    The plain gate answers "is it green now?" — which a task that was
    ALREADY green on base passes trivially, proving nothing (the
    2026-06-12 Finding 1 failure: a deprecation-warning "fix" that edited
    no file still passed, because a warning fails neither ruff nor pytest).
    This report adds the missing half: the same gate must have been RED on
    the base ref. Only a real red→green transition is gate-visible.
    """

    before: VerificationReport | None
    after: VerificationReport
    transition: str
    error: str | None = None

    @property
    def gate_visible(self) -> bool:
        return self.transition == RED_TO_GREEN

    def summary(self) -> str:
        if self.transition == RED_TO_GREEN:
            return "GATE-VISIBLE — base ✗ → change ✓ (real red→green transition)"
        if self.transition == GREEN_TO_GREEN:
            return (
                "GATE-INVISIBLE — base already ✓; the change proves nothing. "
                "Make the gate red on base first (e.g. a failing test, or "
                "`-W error` so a warning counts as failure)."
            )
        if self.transition == STILL_RED:
            return "STILL-RED — change did not make the gate green: " + self.after.summary()
        return f"BASE-ERROR — could not evaluate base ref: {self.error}"


def classify_gate_transition(
    repo_root: Path | str,
    base_ref: str,
    *,
    checks: list[tuple[str, list[str]]] | None = None,
    test_target: str | None = None,
    ruff_paths: list[str] | None = None,
    timeout: float = 600.0,
) -> GateVisibilityReport:
    """Classify whether the worktree's change moved the gate from red→green.

    Runs the gate on the current worktree (must end green) AND on a
    throwaway ``git worktree`` checkout of ``base_ref`` (must have been
    red). Never raises — a base it cannot evaluate is :data:`BASE_ERROR`,
    not an exception (matches the module charter).

    The CRAWL picker (ADR 0182) calls this at task-pick time to reject
    gate-invisible specs before dispatching the agent.
    """
    root = Path(repo_root)
    after = verify_change(
        root, checks=checks, test_target=test_target,
        ruff_paths=ruff_paths, timeout=timeout,
    )

    before = _verify_base_ref(
        root, base_ref, checks=checks, test_target=test_target,
        ruff_paths=ruff_paths, timeout=timeout,
    )
    if before is None:
        return GateVisibilityReport(
            before=None, after=after, transition=BASE_ERROR,
            error=f"could not check out base ref {base_ref!r} in a worktree",
        )

    if not after.ok:
        transition = STILL_RED
    elif before.ok:
        transition = GREEN_TO_GREEN
    else:
        transition = RED_TO_GREEN
    return GateVisibilityReport(before=before, after=after, transition=transition)


def verify_at_ref(
    repo_root: Path | str,
    ref: str,
    *,
    checks: list[tuple[str, list[str]]] | None = None,
    test_target: str | None = None,
    ruff_paths: list[str] | None = None,
    timeout: float = 600.0,
) -> VerificationReport | None:
    """Run the gate against ``ref`` in a throwaway worktree (public surface).

    The CRAWL backlog picker (ADR 0182) uses this at pick time: a spec's
    gate must be RED on base — a gate already green on base is
    gate-invisible (the change could no-op and still "pass"), so the picker
    rejects the spec before dispatching the agent. Returns ``None`` when the
    ref cannot be materialised.
    """
    return _verify_base_ref(
        Path(repo_root), ref, checks=checks, test_target=test_target,
        ruff_paths=ruff_paths, timeout=timeout,
    )


def _verify_base_ref(
    repo_root: Path,
    base_ref: str,
    *,
    checks: list[tuple[str, list[str]]] | None,
    test_target: str | None,
    ruff_paths: list[str] | None,
    timeout: float,
) -> VerificationReport | None:
    """Run the gate against ``base_ref`` in a detached throwaway worktree.

    Returns the base's :class:`VerificationReport`, or ``None`` if the ref
    could not be materialised (unknown ref, not a git repo, …).

    PERF NOTE (CRAWL picker follow-up): the fresh worktree has no ``.venv``,
    so a ``uv run`` check rebuilds the environment there (tens of seconds on
    first use) — fine for a one-shot pick-time check, but the picker should
    reuse the parent venv (e.g. inherit ``VIRTUAL_ENV`` / narrow the base
    check to ruff-only) before calling this in a loop.
    """
    tmp = tempfile.mkdtemp(prefix=".gate-base-")
    try:
        add = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "--detach", tmp, base_ref],
            capture_output=True, text=True, timeout=120,
        )
        if add.returncode != 0:
            return None
        return verify_change(
            Path(tmp), checks=checks, test_target=test_target,
            ruff_paths=ruff_paths, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", tmp],
            capture_output=True, text=True,
        )
        shutil.rmtree(tmp, ignore_errors=True)
