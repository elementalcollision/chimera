"""`chimera critic-calibrate` command handler — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations

import sys


def _cmd_critic_calibrate(args) -> int:
    """`chimera critic-calibrate` — measure the critic's error rates on a
    labelled change set. Prints the confusion matrix + false-approve rate
    (ADR 0160). Exit 0 if no unfaithful change was approved (false-approve == 0),
    else 1 — a false approval is the failure that matters."""
    from .._async_loop import run_on_persistent_loop
    from ..core import ChimeraLoop
    from ..core.critic import review_change
    from ..core.critic_calibration import default_cases, run_calibration
    from ..providers.tiers import Provider as ProviderKind

    loop = ChimeraLoop()
    providers = loop._act.providers if loop._act is not None else {}
    provider = providers.get(ProviderKind.ANTHROPIC)
    if provider is None:
        print("chimera critic-calibrate: no Anthropic provider available.",
              file=sys.stderr)
        return 2

    async def _review(case):
        return await review_change(
            case.diff, provider=provider, model_id=args.model, goal=case.goal,
            docstring=case.docstring, faithfulness=case.faithfulness,
        )

    result = run_on_persistent_loop(run_calibration(default_cases(), _review))
    print(result.summary())

    # ADR 0162: persist the result so the in-loop critic gate can verify the
    # calibration-gated-activation invariant (enforce only while false-approve==0)
    # and `chimera doctor` can surface it. Best-effort — never fail the verb.
    try:
        from pathlib import Path as _Path

        from ..core.critic_gate import write_calibration_record
        write_calibration_record(
            _Path.cwd(), total=result.total, false_approve=result.false_approve,
            false_reject=result.false_reject, accuracy=result.accuracy,
            model=args.model,
        )
    except Exception:
        pass

    return 0 if result.false_approve == 0 else 1
