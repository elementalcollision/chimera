"""Assembler tier escalation (v4.6, ADR 0029).

Mirror of the v3.11 ACT ladder pattern: when ``assemble_skill`` →
``validate_skill`` scores below the activation threshold, retry on
the next tier up. The default ladder is ``("sonnet", "opus")`` —
sonnet first because that's what ``assemble_skill`` defaulted to in
v1.2, opus as the safety net.

The helper records per-attempt outcomes via the same
``ladder_outcomes`` table the ACT executor uses (``task_type =
"skill_assembly"``), so dashboards already surface escalations.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from ..providers import Provider
from ..providers.tiers import Provider as ProviderKind
from .assembly import AssembledSkill, assemble_skill
from .critique import critique_and_revise
from .spec import SkillSpec
from .validation import ValidationResult, validate_skill

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttemptOutcome:
    tier: str
    assembled_ok: bool
    validation_score: float
    validation_ok: bool
    failure_reason: str | None
    revised: bool = False  # whether critique-and-revise was applied
    revised_score: float | None = None


@dataclass
class LadderResult:
    """The first passing (assembled, validation) pair, or the last attempt."""

    assembled: AssembledSkill
    validation: ValidationResult
    attempts: list[AttemptOutcome]
    winning_tier: str | None


async def assemble_with_escalation(
    spec: SkillSpec,
    *,
    providers: dict[ProviderKind, Provider],
    db: sqlite3.Connection,
    cycle: int,
    tiers: Sequence[str] = ("sonnet", "opus"),
    max_tokens: int = 2048,
) -> LadderResult:
    """Walk the tier ladder; stop on first tier whose output validates."""
    last_assembled: AssembledSkill | None = None
    last_validation: ValidationResult | None = None
    attempts: list[AttemptOutcome] = []

    for tier in tiers:
        logger.info("assembler: attempting tier=%s", tier)
        assembled = await assemble_skill(
            spec,
            providers=providers,
            db=db,
            cycle=cycle,
            tier=tier,
            max_tokens=max_tokens,
        )
        if not assembled.ok:
            attempts.append(
                AttemptOutcome(
                    tier=tier,
                    assembled_ok=False,
                    validation_score=0.0,
                    validation_ok=False,
                    failure_reason=assembled.failure_reason,
                )
            )
            last_assembled = assembled
            continue

        validation = await validate_skill(assembled)
        last_assembled = assembled
        last_validation = validation
        if validation.ok:
            attempts.append(
                AttemptOutcome(
                    tier=tier,
                    assembled_ok=True,
                    validation_score=validation.score,
                    validation_ok=True,
                    failure_reason=None,
                )
            )
            return LadderResult(
                assembled=assembled,
                validation=validation,
                attempts=attempts,
                winning_tier=tier,
            )

        # v4.7: one critique-and-revise pass on this tier before escalating.
        logger.info(
            "ladder: tier=%s validation %d/%d (score=%.2f); attempting revise",
            tier, validation.passed, validation.total, validation.score,
        )
        revised = await critique_and_revise(
            spec, assembled, validation,
            providers=providers, db=db, cycle=cycle, tier=tier,
            max_tokens=max_tokens,
        )
        if revised is not None and revised.ok:
            revised_val = await validate_skill(revised)
            if revised_val.ok:
                attempts.append(
                    AttemptOutcome(
                        tier=tier,
                        assembled_ok=True,
                        validation_score=validation.score,
                        validation_ok=False,
                        failure_reason=validation.failure_reason,
                        revised=True,
                        revised_score=revised_val.score,
                    )
                )
                return LadderResult(
                    assembled=revised,
                    validation=revised_val,
                    attempts=attempts,
                    winning_tier=tier,
                )
            # Revision was structurally fine but still didn't pass —
            # carry the better of the two scores forward.
            if revised_val.score > validation.score:
                last_assembled = revised
                last_validation = revised_val
            attempts.append(
                AttemptOutcome(
                    tier=tier,
                    assembled_ok=True,
                    validation_score=validation.score,
                    validation_ok=False,
                    failure_reason=revised_val.failure_reason,
                    revised=True,
                    revised_score=revised_val.score,
                )
            )
        else:
            attempts.append(
                AttemptOutcome(
                    tier=tier,
                    assembled_ok=True,
                    validation_score=validation.score,
                    validation_ok=False,
                    failure_reason=validation.failure_reason,
                    revised=False,
                )
            )

    # Exhausted all tiers — return the last attempt so the caller can
    # mark the mutation failed with the most-recent failure details.
    if last_validation is None:
        last_validation = ValidationResult(
            ok=False,
            score=0.0,
            passed=0,
            total=0,
            failure_reason="assembly failed at every tier",
        )
    return LadderResult(
        assembled=last_assembled or AssembledSkill(spec=spec, ok=False),
        validation=last_validation,
        attempts=attempts,
        winning_tier=None,
    )
