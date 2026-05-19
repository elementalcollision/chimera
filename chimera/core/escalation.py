"""PR #58 escalation — write-intent miss correction prompt + one-tier-up retry.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)":

When a task that requires writes finishes without producing the expected
write_targets (silent failure or partial), inject a correction prompt and
retry one tier up the cost ladder (haiku → sonnet → opus).

This module is pure — no provider calls. The orchestrator wires the
correction prompt back into the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_TIER_ORDER: tuple[Literal["haiku", "sonnet", "opus"], ...] = ("haiku", "sonnet", "opus")


@dataclass(frozen=True)
class EscalationPlan:
    """What the ACT phase should do next."""

    correction_prompt: str
    next_tier: str          # haiku | sonnet | opus
    retry: bool             # if False, the task is marked failed and the loop continues


def next_tier_up(current_tier: str) -> str:
    """Return the next tier in the cost ladder, or stay at the top."""
    if current_tier not in _TIER_ORDER:
        return "sonnet"
    idx = _TIER_ORDER.index(current_tier)
    return _TIER_ORDER[min(idx + 1, len(_TIER_ORDER) - 1)]


def build_correction_prompt(
    task_text: str,
    expected_paths: list[str],
    actual_writes: list[str],
) -> str:
    """The PR #58 correction message injected on retry."""
    expected_block = (
        ", ".join(sorted(expected_paths)) if expected_paths else "(none extracted)"
    )
    actual_block = (
        ", ".join(sorted(actual_writes)) if actual_writes else "NOTHING was written"
    )
    return (
        "Correction required.\n"
        f"\nThe task was:\n  {task_text!r}\n"
        f"\nYou were expected to write to:\n  {expected_block}\n"
        f"\nActual writes:\n  {actual_block}\n"
        "\nThis is a silent or partial failure. Retry the task and call the "
        "appropriate write tool against each expected path. Do not respond "
        "with prose alone — every expected path must appear in your tool calls."
    )


def build_escalation_plan(
    task_text: str,
    expected_paths: list[str],
    actual_writes: list[str],
    current_tier: str,
    retries_used: int,
    max_retries: int = 1,
) -> EscalationPlan:
    """Decide what to do after a write-intent miss.

    First miss → correction prompt + one-tier-up retry.
    Subsequent miss → mark failed (the loop continues, the operator decides).
    """
    correction = build_correction_prompt(task_text, expected_paths, actual_writes)
    if retries_used >= max_retries:
        return EscalationPlan(correction_prompt=correction, next_tier=current_tier, retry=False)
    return EscalationPlan(
        correction_prompt=correction,
        next_tier=next_tier_up(current_tier),
        retry=True,
    )
