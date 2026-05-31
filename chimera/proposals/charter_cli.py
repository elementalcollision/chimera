"""Orchestration for the ``chimera charter`` CLI verb (S1 follow-up).

One command end-to-end: generate a self-charter for a goal (ADR 0153), gate it
on the teeth check (ADR 0152), and — if it passes — materialize the build-soak
inputs (ADR 0154) and print the human-review packet. Pure of argparse so it is
testable with a stub provider; the CLI handler supplies a real provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .charter import generate_charter
from .charter_materialize import format_charter_packet, materialize_charter


def run_charter(
    goal: str,
    *,
    provider,
    model_id: str,
    repo_root: Path | str,
    prefix: str = "charter",
    threshold: float = 0.8,
    write: bool = True,
) -> tuple[int, str]:
    """Generate → teeth-gate → materialize → packet.

    Returns ``(exit_code, output)``. Exit 0 when a valid charter was produced
    (and materialized unless ``write=False``); exit 1 when the model emitted no
    usable charter or the test failed the teeth gate (the reason is the output).
    """
    bundle, val = asyncio.run(
        generate_charter(goal, provider=provider, model_id=model_id, threshold=threshold)
    )
    if bundle is None:
        return 1, f"charter rejected: {val.reason}"
    if not val.ok:
        score = f"{val.teeth.teeth_score:.2f}" if val.teeth else "n/a"
        return 1, (
            f"charter rejected (the self-written test is not trustworthy): "
            f"{val.reason}\n  goal: {goal}\n  teeth: {score}\n"
            "No artifacts written."
        )
    art = materialize_charter(bundle, repo_root=repo_root, prefix=prefix, write=write)
    teeth = val.teeth.teeth_score if val.teeth else None
    packet = format_charter_packet(bundle, art, teeth_score=teeth)
    if write:
        launch = (
            f"CHARTER_MODULE={bundle.module_name} "
            f"CHARTER_TARGET={art.target_module_path} "
            f"CHARTER_TEST={art.test_path} \\\n"
            f"  CHARTER_GOAL={goal!r} bash scripts/charter_build_soak.sh"
        )
        packet += (
            f"\n\nWrote:\n  {art.test_path}\n  {art.design_path}\n\n"
            f"To build + self-commit (after committing the two files to a branch):\n"
            f"  {launch}"
        )
    else:
        packet += "\n\n(preview — no files written)"
    return 0, packet
