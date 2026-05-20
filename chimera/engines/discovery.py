"""DiscoveryEngine — morning distillation of recent activity.

Per Reggio: a Haiku call summarises the last few cycles into a
"Morning Discovery" bullet list appended to today's CHRONICLE entry.
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


_PROMPT_TEMPLATE = """You are Chimera's Morning Discovery engine.

Read the recent activity below and distill it into 3-5 short bullet points capturing:
- new themes or topics Chimera engaged with,
- patterns of repetition or stuck behaviour,
- notable failures or surprising successes.

Be terse. One bullet per line, leading with `-`. No preamble.

---

Recent api activity (last few cycles):
{history}

Current INBOX (open tasks):
{inbox}
"""


class DiscoveryEngine(EngineBase):
    name = "discovery"

    def __init__(
        self,
        *,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        mind_dir: Path,
        chronicle: ChronicleManager,
        tier: str = "haiku",
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

        # v4.69 (ADR 0088 §P1): open the unified engine_runs row first
        # so a crash still leaves a visible "running" row.
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

        # v4.70 (ADR 0089): signal-density gate. Skip when recent
        # cycles don't have enough api activity to distill.
        from ..core.engine_gates import discovery_gate
        gate = discovery_gate(self._db, cycle=cycle)
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
        history_block = recent_history(self._db, current_cycle=cycle, last_n_cycles=5).render()
        inbox_path = self._mind_dir / "INBOX.md"
        inbox_text = inbox_path.read_text(encoding="utf-8") if inbox_path.exists() else "(empty)"
        prompt = _PROMPT_TEMPLATE.format(history=history_block, inbox=inbox_text)

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
                task_type="discovery",
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
            task_type="discovery",
        )

        body = response.text.strip() or "(no observations)"
        self._chronicle.upsert_section(section_name="Morning Discovery", body=body)
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
