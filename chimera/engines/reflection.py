"""ReflectionEngine — evening distillation of the day.

Per Reggio: a Sonnet call writes a brief reflective narrative drawing on
today's CHRONICLE entries (Morning Discovery, Midday Curiosity) and the
day's api-call summary. Output replaces today's "Evening Reflection"
sub-section.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ..memory import record_api_call, record_ladder_outcome
from ..prompts import recent_history
from ..providers import Message, Provider
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import select_rung
from .base import EngineBase, EngineResult
from .chronicle import ChronicleManager

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = """You are Chimera's Evening Reflection engine.

Today's chronicle so far (may be partial):

{day_so_far}

Today's api activity summary:
{history}

Write a brief Evening Reflection (under 200 words) covering:
- what got done today,
- one thing learned,
- one thing to do differently tomorrow.

Use Chimera's first-person voice. No preamble. Plain prose; bullets optional.
"""


class ReflectionEngine(EngineBase):
    name = "reflection"

    def __init__(
        self,
        *,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        mind_dir: Path,
        chronicle: ChronicleManager,
        tier: str = "sonnet",
        max_tokens: int = 1024,
    ) -> None:
        self._providers = providers
        self._db = db
        self._mind_dir = Path(mind_dir)
        self._chronicle = chronicle
        self._tier = tier
        self._max_tokens = max_tokens

    async def run(self, *, cycle: int) -> EngineResult:
        from ..core.mind import utc_now_iso

        rung = select_rung(self._tier)
        provider = self._providers.get(rung.config.provider)
        if provider is None:
            return EngineResult(
                engine=self.name,
                skipped=True,
                fired_at=utc_now_iso(),
                failure_reason=f"no provider for {rung.config.provider}",
            )

        model_id = (
            rung.config.model_id
            if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )
        day_so_far = self._chronicle.day_section() or "(empty)"
        history_block = recent_history(self._db, current_cycle=cycle, last_n_cycles=24).render()
        prompt = _PROMPT_TEMPLATE.format(day_so_far=day_so_far, history=history_block)

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
                task_type="reflection",
            )
            return EngineResult(
                engine=self.name,
                skipped=False,
                fired_at=utc_now_iso(),
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
            task_type="reflection",
        )

        body = response.text.strip() or "(no reflection)"
        self._chronicle.upsert_section(section_name="Evening Reflection", body=body)
        return EngineResult(
            engine=self.name,
            skipped=False,
            fired_at=utc_now_iso(),
            artifacts=[str(self._chronicle.path)],
            api_call_count=1,
            summary=body[:200],
        )
