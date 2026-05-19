"""Critique-and-revise feedback loop (v4.7, ADR 0030).

When ``validate_skill`` returns ``ok=False`` on an assembled skill,
feed the handler code AND the per-sample failure outcomes back to the
LLM, ask for a focused fix in the same three-fenced-block format,
re-parse, and re-validate. One revision round per tier — the ladder
keeps the outer escalation in v4.6.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from ..memory import record_api_call, record_ladder_outcome
from ..providers import Message, Provider
from ..providers.tiers import LadderRung
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import select_rung
from .assembly import AssembledSkill, parse_assembly_response
from .spec import SkillSpec
from .validation import ValidationResult

logger = logging.getLogger(__name__)


CRITIQUE_PROMPT_TEMPLATE = """You are Chimera's skill REVISER.

The skill assembler produced a handler that FAILED validation. Below
is the brief, the failed code, and the per-sample failure detail.
Produce a REVISED handler that fixes the failures.

Respond with the same three fenced blocks in the same order
(`schema`, `python`, `samples`). NO prose, NO extra fences. Keep
samples whose `ok=true`; rewrite samples whose `ok=false` if the
sample itself was wrong, OR fix the handler so the same samples pass
— prefer fixing the handler.

---

## Brief

Skill name: {name}
Description: {description}

Brief:
{brief}

## Failed handler

```python
{handler_code}
```

## Per-sample outcomes (validator's verdict)

```json
{outcomes_json}
```

## Last validation failure reason

{failure_reason}

---

Now produce the corrected `schema` / `python` / `samples` fenced blocks.
"""


def build_critique_prompt(
    spec: SkillSpec, assembled: AssembledSkill, validation: ValidationResult
) -> str:
    outcomes_json = json.dumps(validation.sample_outcomes, indent=2)[:4000]
    return CRITIQUE_PROMPT_TEMPLATE.format(
        name=spec.name,
        description=spec.description,
        brief=spec.brief,
        handler_code=assembled.handler_code.strip(),
        outcomes_json=outcomes_json,
        failure_reason=validation.failure_reason or "(none)",
    )


async def critique_and_revise(
    spec: SkillSpec,
    assembled: AssembledSkill,
    validation: ValidationResult,
    *,
    providers: dict[ProviderKind, Provider],
    db: sqlite3.Connection,
    cycle: int,
    tier: str,
    max_tokens: int = 2048,
) -> AssembledSkill | None:
    """One revision pass. Returns the revised :class:`AssembledSkill` or
    ``None`` if the reviser failed entirely."""
    rung: LadderRung = select_rung(tier)
    provider = providers.get(rung.config.provider)
    if provider is None:
        logger.warning("critique: no provider for tier %s", tier)
        return None
    model_id = (
        rung.config.model_id
        if rung.config.provider is ProviderKind.ANTHROPIC
        else rung.config.openrouter_model_id
    )
    prompt = build_critique_prompt(spec, assembled, validation)
    try:
        response = await provider.complete_with_tools(
            messages=[Message.user(prompt)],
            model_id=model_id,
            tools=[],
            max_tokens=max_tokens,
        )
    except Exception as exc:
        record_api_call(
            db, cycle=cycle, provider=provider.name, model_id=model_id, error=str(exc)
        )
        record_ladder_outcome(
            db, cycle=cycle, tier=tier, rung_model_id=rung.label,
            outcome="non_retriable", task_type="skill_critique",
        )
        return None

    record_api_call(
        db,
        cycle=cycle,
        provider=provider.name,
        model_id=response.model_id,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=response.latency_ms,
        finish_reason=response.stop_reason,
    )
    revised = parse_assembly_response(response.text, spec)
    record_ladder_outcome(
        db,
        cycle=cycle,
        tier=tier,
        rung_model_id=rung.label,
        outcome="success" if revised.ok else "retry_exhausted",
        task_type="skill_critique",
    )
    return revised if revised.ok else None
