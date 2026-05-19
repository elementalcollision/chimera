"""PLAN-phase planner — calls Opus every Nth cycle, emits dedup'd proposals.

Per ADR 0003 §"Phase 3 PLAN" + pillar-creativity.md Patterns 1–2.

The planner is a thin wrapper around the existing provider abstraction:

  1. Decide whether to plan this cycle (``cycle % every_n == 0``).
  2. Build a planning prompt (open tasks + recent history).
  3. Call the Opus tier via ``complete_with_tools`` (no tools attached —
     planning is pure text generation).
  4. Parse the ```tasks block, cap at ``MAX_PROPOSED_TASKS_PER_PLAN``.
  5. Dedup against the existing INBOX.
  6. Return the survivors. The caller appends them to ``mind/INBOX.md``.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from ..memory import record_api_call, record_ladder_outcome
from ..prompts import recent_history
from ..proposals import (
    MAX_PROPOSED_TASKS_PER_PLAN,
    ProposedTask,
    build_plan_prompt,
    dedup,
    extract_proposals,
)
from ..providers import Message, Provider
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import select_rung

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanResult:
    cycle: int
    skipped: bool
    raw_text: str
    proposals: list[ProposedTask]
    api_call_count: int = 0
    failure_reason: str | None = None


class Planner:
    """Opus-tier strategic planner."""

    def __init__(
        self,
        *,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        tier: str = "opus",
        max_tokens: int = 4096,
    ) -> None:
        self._providers = providers
        self._db = db
        self._tier = tier
        self._max_tokens = max_tokens

    async def maybe_plan(
        self,
        *,
        cycle: int,
        every_n: int,
        open_tasks: list[str],
    ) -> PlanResult:
        if cycle <= 0 or cycle % every_n != 0:
            return PlanResult(cycle=cycle, skipped=True, raw_text="", proposals=[])

        rung = select_rung(self._tier)
        provider = self._providers.get(rung.config.provider)
        if provider is None:
            logger.info("PLAN skipped: no provider for %s", rung.config.provider)
            return PlanResult(
                cycle=cycle,
                skipped=True,
                raw_text="",
                proposals=[],
                failure_reason=f"no provider for {rung.config.provider}",
            )

        model_id = (
            rung.config.model_id
            if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )
        history_block = recent_history(self._db, current_cycle=cycle).render()
        prompt = build_plan_prompt(
            cycle=cycle,
            open_tasks=open_tasks,
            recent_summary=history_block,
        )

        try:
            response = await provider.complete_with_tools(
                messages=[Message.user(prompt)],
                model_id=model_id,
                tools=[],
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            record_api_call(
                self._db,
                cycle=cycle,
                provider=provider.name,
                model_id=model_id,
                error=str(exc),
            )
            record_ladder_outcome(
                self._db,
                cycle=cycle,
                tier=self._tier,
                rung_model_id=rung.label,
                outcome="non_retriable",
                task_type="plan",
            )
            return PlanResult(
                cycle=cycle,
                skipped=False,
                raw_text="",
                proposals=[],
                failure_reason=str(exc),
            )

        record_api_call(
            self._db,
            cycle=cycle,
            provider=provider.name,
            model_id=response.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            finish_reason=response.stop_reason,
        )
        record_ladder_outcome(
            self._db,
            cycle=cycle,
            tier=self._tier,
            rung_model_id=rung.label,
            outcome="success",
            task_type="plan",
        )

        raw_proposals = extract_proposals(response.text)
        survivors = dedup(raw_proposals, existing_tasks=open_tasks)[
            :MAX_PROPOSED_TASKS_PER_PLAN
        ]
        return PlanResult(
            cycle=cycle,
            skipped=False,
            raw_text=response.text,
            proposals=survivors,
            api_call_count=1,
        )
