"""Assembly stage — Sonnet generates handler code + schema + samples.

The model's output uses three named fenced blocks: ``schema`` (JSON),
``python`` (the handler), and ``samples`` (JSON array). On parse failure
the assembled skill is :class:`AssembledSkill` with ``ok=False``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..memory import record_api_call, record_ladder_outcome
from ..providers import Message, Provider
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import resolve_rung
from .spec import SkillSpec


_FENCE_RE = lambda name: re.compile(  # noqa: E731 — small, clear lambda
    rf"```{name}\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)


@dataclass
class AssembledSkill:
    spec: SkillSpec
    ok: bool
    schema: dict[str, Any] = field(default_factory=dict)
    handler_code: str = ""
    samples: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    failure_reason: str | None = None
    api_call_count: int = 0


ASSEMBLY_PROMPT_TEMPLATE = """You are Chimera's skill assembler.

Given a brief, produce three artifacts in EXACTLY three fenced blocks
labelled `schema`, `python`, `samples` — in that order, with NO prose
between them and NO additional fences.

Handler contract:
- Single function: `async def handle(args: dict, context) -> str:`
- ONLY Python stdlib (no third-party imports).
- NO subprocess, NO network (no `socket`, `urllib`, `http`, `requests`),
  NO `eval`, NO `exec`, NO `__import__`, NO writes outside cwd.
- Return a `str`. Be deterministic and pure where possible.
- Handle missing/invalid args by raising `ValueError(<clear message>)`.

Sample contract:
- A JSON array of `{{"input": <dict>, "expected_substring": <str>}}`.
- 3 samples covering: a typical case, an edge case, and an error case
  (where the handler raises `ValueError`; expected_substring may be the
  error keyword you raise, since validator captures stderr).

---

## Worked example

Brief: A skill named `reverse_string` that takes `{{"text": str}}` and
returns the reversed string.

```schema
{{"type": "function", "function": {{"name": "reverse_string", "description": "Reverse a string.", "parameters": {{"type": "object", "properties": {{"text": {{"type": "string"}}}}, "required": ["text"]}}}}}}
```

```python
async def handle(args, context):
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return text[::-1]
```

```samples
[
  {{"input": {{"text": "hello"}}, "expected_substring": "olleh"}},
  {{"input": {{"text": ""}}, "expected_substring": ""}},
  {{"input": {{"text": 42}}, "expected_substring": "must be a string"}}
]
```

---

## Now produce the same three blocks for THIS brief

Skill name: {name}
Skill description: {description}

Brief:
{brief}
"""


def build_assembly_prompt(spec: SkillSpec) -> str:
    return ASSEMBLY_PROMPT_TEMPLATE.format(
        name=spec.name,
        description=spec.description,
        brief=spec.brief,
    )


def parse_assembly_response(text: str, spec: SkillSpec) -> AssembledSkill:
    """Pull the three fenced blocks out of the model's response."""
    schema_match = _FENCE_RE("schema").search(text)
    code_match = _FENCE_RE("python").search(text)
    samples_match = _FENCE_RE("samples").search(text)

    if not schema_match or not code_match or not samples_match:
        return AssembledSkill(
            spec=spec,
            ok=False,
            raw_text=text,
            failure_reason="missing one of the schema/python/samples fenced blocks",
        )

    try:
        schema = json.loads(schema_match.group(1))
    except json.JSONDecodeError as exc:
        return AssembledSkill(
            spec=spec, ok=False, raw_text=text, failure_reason=f"schema JSON parse: {exc}"
        )

    try:
        samples = json.loads(samples_match.group(1))
    except json.JSONDecodeError as exc:
        return AssembledSkill(
            spec=spec, ok=False, raw_text=text, failure_reason=f"samples JSON parse: {exc}"
        )
    if not isinstance(samples, list) or not samples:
        return AssembledSkill(
            spec=spec, ok=False, raw_text=text, failure_reason="samples must be a non-empty list"
        )

    handler_code = code_match.group(1).strip() + "\n"
    if "async def handle" not in handler_code:
        return AssembledSkill(
            spec=spec, ok=False, raw_text=text,
            failure_reason="python block missing `async def handle`",
        )

    return AssembledSkill(
        spec=spec,
        ok=True,
        schema=schema,
        handler_code=handler_code,
        samples=samples,
        raw_text=text,
    )


async def assemble_skill(
    spec: SkillSpec,
    *,
    providers: dict[ProviderKind, Provider],
    db: sqlite3.Connection,
    cycle: int,
    tier: str = "sonnet",
    max_tokens: int = 2048,
) -> AssembledSkill:
    """Call the assembler tier to produce the handler + schema + samples."""
    rung = resolve_rung(tier)
    provider = providers.get(rung.config.provider)
    if provider is None:
        return AssembledSkill(
            spec=spec,
            ok=False,
            failure_reason=f"no provider for {rung.config.provider}",
        )
    model_id = (
        rung.config.model_id
        if rung.config.provider is ProviderKind.ANTHROPIC
        else rung.config.openrouter_model_id
    )
    prompt = build_assembly_prompt(spec)
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
            outcome="non_retriable", task_type="skill_assembly",
        )
        return AssembledSkill(spec=spec, ok=False, failure_reason=str(exc), api_call_count=0)

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
    record_ladder_outcome(
        db,
        cycle=cycle,
        tier=tier,
        rung_model_id=rung.label,
        outcome="success",
        task_type="skill_assembly",
    )
    out = parse_assembly_response(response.text, spec)
    out.api_call_count = 1
    return out
