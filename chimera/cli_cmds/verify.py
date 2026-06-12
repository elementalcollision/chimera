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

    from ..core.repo_verify import (
        GREEN_TO_GREEN,
        RED_TO_GREEN,
        classify_gate_transition,
        verify_change,
    )

    # Gate-visibility mode (ADR 0182): require a real red→green transition,
    # not merely green-now (which a spec already passing on base satisfies
    # without doing anything — the 2026-06-12 Finding 1 failure).
    if getattr(args, "base", None):
        gv = classify_gate_transition(
            Path.cwd(),
            base_ref=args.base,
            test_target=args.test,
            ruff_paths=args.ruff,
            timeout=args.timeout,
        )
        print(gv.summary())
        if gv.transition == RED_TO_GREEN:
            return 0
        for check in gv.after.failed:
            print(f"\n── {check.name} (exit {check.returncode}) ──", file=sys.stderr)
            print(check.detail, file=sys.stderr)
        # Distinct exit so a caller can tell "gate-invisible spec" (3) from
        # "change incomplete / broke the gate" (1).
        return 3 if gv.transition == GREEN_TO_GREEN else 1

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
