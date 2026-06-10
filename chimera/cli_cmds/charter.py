"""`chimera charter` command handler — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations

import sys
from pathlib import Path


def _cmd_charter(args) -> int:
    """`chimera charter "<goal>"` — self-author a teeth-validated charter."""
    from ..core import ChimeraLoop
    from ..proposals.charter_cli import run_charter
    from ..providers.tiers import Provider as ProviderKind
    from ..providers.tiers import select_rung

    loop = ChimeraLoop()
    try:
        providers = loop._act.providers if loop._act is not None else {}
        if not providers:
            print(
                "chimera charter: no provider available (set ANTHROPIC_API_KEY "
                "or OPENROUTER_API_KEY).",
                file=sys.stderr,
            )
            return 2
        rung = select_rung(args.tier)
        provider = providers.get(rung.config.provider)
        if provider is None:
            print(
                f"chimera charter: no provider for tier {args.tier!r} "
                f"({rung.config.provider}).",
                file=sys.stderr,
            )
            return 2
        model_id = (
            rung.config.model_id
            if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )
        code, out = run_charter(
            args.goal,
            provider=provider,
            model_id=model_id,
            repo_root=Path.cwd(),
            prefix=args.prefix,
            threshold=args.threshold,
            write=not args.no_write,
        )
        print(out)
        return code
    finally:
        loop.close()
