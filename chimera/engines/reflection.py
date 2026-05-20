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
        from ..memory import finish_engine_run, start_engine_run

        # v4.69 (ADR 0088 §P1): unified engine telemetry.
        run_id = start_engine_run(self._db, engine=self.name, cycle=cycle)

        rung = select_rung(self._tier)
        provider = self._providers.get(rung.config.provider)
        if provider is None:
            reason = f"no provider for {rung.config.provider}"
            finish_engine_run(
                self._db, run_id, status="skipped", skip_reason=reason,
            )
            return EngineResult(
                engine=self.name,
                skipped=True,
                fired_at=utc_now_iso(),
                failure_reason=reason,
            )

        # v4.70 (ADR 0089): skip on quiet days. Reflection has a
        # documented tendency to write generic "today was quiet"
        # narratives on empty days (see 2026-05-19 chronicle).
        from ..core.engine_gates import reflection_gate
        gate = reflection_gate(self._db, cycle=cycle)
        if not gate.allow:
            finish_engine_run(
                self._db, run_id, status="skipped", skip_reason=gate.reason,
            )
            return EngineResult(
                engine=self.name,
                skipped=True,
                fired_at=utc_now_iso(),
                failure_reason=gate.reason,
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
                caller=self.name,
            )
            record_ladder_outcome(
                self._db,
                cycle=cycle,
                tier=self._tier,
                rung_model_id=rung.label,
                outcome="non_retriable",
                task_type="reflection",
            )
            finish_engine_run(
                self._db, run_id, status="failed", skip_reason=str(exc),
                api_calls=1,
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
            caller=self.name,
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
        finish_engine_run(
            self._db, run_id, status="success",
            api_calls=1,
            tokens_in=response.input_tokens or 0,
            tokens_out=response.output_tokens or 0,
            chronicle_added=len(body.splitlines()),
            summary=body[:200],
        )
        return EngineResult(
            engine=self.name,
            skipped=False,
            fired_at=utc_now_iso(),
            artifacts=[str(self._chronicle.path)],
            api_call_count=1,
            summary=body[:200],
        )
