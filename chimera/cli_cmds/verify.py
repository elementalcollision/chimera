"""`chimera verify` command handler — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations

import sys


def _cmd_verify(args) -> int:
    """`chimera verify` — run the repo's real checks (ruff + pytest) over the
    current tree and print a structured pass/fail (B1 / ADR 0158).

    Exit 0 when every check passes, 1 when any fails. The same gate a B-tier
    soak uses as its convergence criterion, exposed so the agent (or operator)
    can run the real pipeline as one command and read the actionable failure
    detail.
    """
    from pathlib import Path

    from ..core.repo_verify import verify_change

    report = verify_change(
        Path.cwd(),
        test_target=args.test,
        ruff_paths=args.ruff,
        timeout=args.timeout,
    )
    print(report.summary())
    for check in report.failed:
        print(f"\n── {check.name} (exit {check.returncode}) ──", file=sys.stderr)
        print(check.detail, file=sys.stderr)
    return 0 if report.ok else 1
