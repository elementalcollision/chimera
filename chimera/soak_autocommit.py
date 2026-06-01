"""Harness-executed deterministic commit for soak phase 2 (ADR 0148).

The v46 re-soak #2 confirmed the commit-not-executed gate (ADR 0147) fires
in-loop — but also proved that an in-loop signal is NECESSARY, not SUFFICIENT:
across 58 ``commit_not_executed`` firings the agent never ran a bare
``git commit``. It reliably AUTHORS, STAGES, and GREENS the deliverable, then
spirals into meta-work (building pre-commit hooks, CONTRIBUTING.md) instead of
committing. The agent's own cycle-158 research said it: ~100% adherence comes
only from "removing the ability to skip" — i.e. the HARNESS commits, not the
agent.

This module is that harness commit. The division of labour is explicit and
honest: the agent authors + stages + greens; the runner deterministically
executes the final ``git commit`` once those content conditions hold. The
ADR 0147 gate remains the detector that proves the commit landed.

Public entry point: :func:`autocommit_if_ready`. Pure-ish (only git + an
optional test subprocess); fully unit-tested against a temp repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Status strings returned by autocommit_if_ready (also the log signal).
ALREADY_COMMITTED = "already_committed"
TEST_FAILING = "test_failing"
NOTHING_TO_COMMIT = "nothing_to_commit"
COMMITTED = "committed"
CRITIC_BLOCKED = "critic_blocked"
ERROR = "error"


def _git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root),
        capture_output=True, text=True, timeout=timeout,
    )


def _has_agent_commit(root: Path, base_ref: str, head_ref: str) -> bool:
    """True if an ``[agent]``-subject commit exists in ``base_ref..head_ref``."""
    log = _git(root, "log", "--format=%s", f"{base_ref}..{head_ref}")
    if log.returncode != 0:
        return False
    return any(
        line.strip().startswith("[agent]")
        for line in (log.stdout or "").splitlines()
    )


def autocommit_if_ready(
    worktree_root: Path | str,
    allowed_files: list[str],
    message: str,
    *,
    test_cmd: list[str] | None = None,
    base_ref: str = "main",
    head_ref: str = "HEAD",
    journal_dir: str = "mind",
) -> str:
    """Deterministically commit the staged-and-green soak deliverable.

    The harness-side counterpart to the agent's author+stage+green: once the
    content conditions hold, the RUNNER executes the commit the agent reliably
    will not. Idempotent and fail-safe — never raises; on any error returns
    :data:`ERROR` so the caller (a soak runner) keeps looping.

    Order of checks (each a clean no-op return, never a commit of bad state):

    1. :data:`ALREADY_COMMITTED` — an ``[agent]`` commit already exists in
       ``base_ref..head_ref``. Idempotent: safe to call every iteration.
    2. :data:`TEST_FAILING` — ``test_cmd`` (if given) exits non-zero. Never
       commit red code. Skipped when ``test_cmd`` is None.
    3. Stage the ``allowed_files`` that exist on disk, plus the ``journal_dir``
       tree (``mind/`` — the operational journal the loop writes between
       cycles, auto-allowed by the soft-sentinel per ADR 0121).
    4. :data:`NOTHING_TO_COMMIT` — nothing is staged after step 3.
    5. :data:`COMMITTED` — ``git commit`` succeeds. ``message`` MUST already
       begin with ``[agent]`` (the autonomous-delivery contract token the
       ADR 0147 gate and the soft-sentinel look for); the caller is expected
       to disclose harness execution in the body.

    Honesty (a locked constraint): this commit is HARNESS-executed. The agent
    authored, staged, and greened the deliverable; it did NOT run ``git
    commit``. The caller's ``message`` body must say so (see ADR 0148).
    """
    try:
        root = Path(worktree_root)
        if _has_agent_commit(root, base_ref, head_ref):
            return ALREADY_COMMITTED
        if test_cmd:
            res = subprocess.run(
                test_cmd, cwd=str(root),
                capture_output=True, text=True, timeout=600,
            )
            if res.returncode != 0:
                return TEST_FAILING
        # Stage the explicit deliverables that exist on disk.
        for rel in allowed_files:
            if (root / rel).exists():
                _git(root, "add", "--", rel)
        # Stage the operational journal tree (auto-allowed, ADR 0121).
        if (root / journal_dir).exists():
            _git(root, "add", "--", journal_dir)
        # Anything staged? `git diff --cached --quiet` exits 1 when staged.
        staged = _git(root, "diff", "--cached", "--quiet")
        if staged.returncode == 0:
            return NOTHING_TO_COMMIT
        # ADR 0162: the in-loop critic gate also guards the harness autocommit
        # path, so enforce-ON covers BOTH commit routes (the agent's git_commit
        # and this fallback). Inert unless CHIMERA_CRITIC_ENFORCE=1.
        import os as _os

        from chimera.core.critic_gate import check_commit_critic, enforce_enabled
        if enforce_enabled():
            import asyncio as _asyncio
            decision = _asyncio.run(check_commit_critic(
                root, goal=_os.environ.get("CHIMERA_TASK_GOAL")))
            if not decision.allowed:
                return CRITIC_BLOCKED
        commit = _git(root, "commit", "-m", message)
        if commit.returncode != 0:
            return ERROR
        return COMMITTED
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return ERROR
