"""Multi-witness critique pool (v4.8, ADR 0031).

Where v4.7 ran one critique-and-revise pass on the same tier that did
the assembly, v4.8 fans the critique out across multiple **witness
tiers** concurrently. Each witness produces an independent revision;
each revision is validated; the highest-scoring revision wins. If
multiple revisions tie, the cheapest tier wins.

Rationale: when a code-gen task is hard, one model + one self-critique
seldom recovers, but a different model reviewing the same failure
often catches what the original missed. The "create, inspect,
witness, critique" pattern the autoresearch mandate asks for.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from ..providers import Provider
from ..providers.tiers import Provider as ProviderKind
from .assembly import AssembledSkill
from .critique import critique_and_revise
from .spec import SkillSpec
from .validation import ValidationResult, validate_skill

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WitnessOutcome:
    tier: str
    revised_ok: bool
    score: float
    failure_reason: str | None


@dataclass
class CrossCritiqueResult:
    best_assembled: AssembledSkill | None
    best_validation: ValidationResult | None
    winning_witness: str | None
    witnesses: list[WitnessOutcome]


async def _one_witness(
    spec: SkillSpec,
    assembled: AssembledSkill,
    validation: ValidationResult,
    *,
    providers: dict[ProviderKind, Provider],
    db: sqlite3.Connection,
    cycle: int,
    tier: str,
    max_tokens: int = 2048,
) -> tuple[WitnessOutcome, AssembledSkill | None, ValidationResult | None]:
    revised = await critique_and_revise(
        spec, assembled, validation,
        providers=providers, db=db, cycle=cycle, tier=tier,
        max_tokens=max_tokens,
    )
    if revised is None:
        return (
            WitnessOutcome(
                tier=tier, revised_ok=False, score=0.0,
                failure_reason="critic returned no parseable revision",
            ),
            None, None,
        )
    revised_val = await validate_skill(revised)
    return (
        WitnessOutcome(
            tier=tier,
            revised_ok=revised_val.ok,
            score=revised_val.score,
            failure_reason=revised_val.failure_reason,
        ),
        revised, revised_val,
    )


async def cross_critique(
    spec: SkillSpec,
    assembled: AssembledSkill,
    validation: ValidationResult,
    *,
    providers: dict[ProviderKind, Provider],
    db: sqlite3.Connection,
    cycle: int,
    witnesses: Sequence[str] = (
        "claude-opus-4-7", "gpt-5.1-codex-max", "gemini-3.1-pro-preview",
    ),
    max_tokens: int = 2048,
) -> CrossCritiqueResult:
    """Fan critique out across ``witnesses`` concurrently.

    Returns the highest-scoring revision (or first that crosses the
    activation threshold). Witnesses are ordered cheapest-first so on
    ties the cheaper tier wins.
    """
    tasks = [
        _one_witness(
            spec, assembled, validation,
            providers=providers, db=db, cycle=cycle, tier=tier,
            max_tokens=max_tokens,
        )
        for tier in witnesses
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outcomes: list[WitnessOutcome] = []
    candidates: list[tuple[float, str, AssembledSkill, ValidationResult]] = []
    for tier, res in zip(witnesses, results):
        if isinstance(res, BaseException):
            outcomes.append(
                WitnessOutcome(
                    tier=tier, revised_ok=False, score=0.0,
                    failure_reason=f"exception: {res}",
                )
            )
            continue
        outcome, revised, revised_val = res
        outcomes.append(outcome)
        if revised is not None and revised_val is not None:
            candidates.append((revised_val.score, tier, revised, revised_val))

    if not candidates:
        return CrossCritiqueResult(
            best_assembled=None,
            best_validation=None,
            winning_witness=None,
            witnesses=outcomes,
        )

    # Sort by score desc, then by witness order (cheaper first) on ties.
    witness_rank = {t: i for i, t in enumerate(witnesses)}
    candidates.sort(key=lambda c: (-c[0], witness_rank[c[1]]))
    best_score, best_tier, best_assembled, best_val = candidates[0]
    return CrossCritiqueResult(
        best_assembled=best_assembled,
        best_validation=best_val,
        winning_witness=best_tier,
        witnesses=outcomes,
    )
