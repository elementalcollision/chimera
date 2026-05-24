"""Deriver — Honcho-inspired structured-output extraction (ADR 0124).

The ReflectionEngine writes a free-form Evening Reflection narrative
into CHRONICLE. That's good for human reading, but downstream code
(witness panels, escalation memory, dashboards) can't reliably query
"what did Chimera learn today?" from prose.

Honcho's "deriver" addresses the same problem in conversational
memory: a single structured-output LLM call per batch returns *typed
conclusions* — explicit facts, deductive inferences, themes — that
downstream tools can index, filter, and surface without re-running an
LLM. See [ADR 0123](../../docs/adr/0123-honcho-inspired-enhancements.md)
for the inspire-don't-integrate framing.

This module is the parsing + schema layer. It does NOT make LLM calls
itself; the caller is responsible for running the provider with
``DERIVER_PROMPT`` and passing the response text to
:func:`parse_conclusions`. Keeping the LLM call out of this module
keeps it provider-agnostic, cheap to test, and trivial to wire into
ReflectionEngine in a follow-up chip without redesign.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


DERIVER_PROMPT = """You are Chimera's structured-output Deriver.

Read the chronicle excerpt below and return STRICT JSON (no preamble,
no markdown fence) with the schema:

{{
  "summary": "<one-sentence summary of the day, under 30 words>",
  "lessons_learned": ["<short statement>", ...],   // 0-5 items
  "improvements_for_tomorrow": ["<short statement>", ...],  // 0-5 items
  "themes": ["<one-or-two-word theme>", ...]   // 0-5 items
}}

Chronicle excerpt:

{day_so_far}

Return ONLY the JSON object. No prose, no explanations, no markdown
code fences."""


@dataclass
class ReflectionConclusions:
    """Typed conclusions derived from a chronicle excerpt.

    All list fields default to empty so a partial / malformed LLM
    response still produces a usable object (with whatever fields the
    parser could extract). ``summary`` is the most-load-bearing field
    and defaults to the empty string.
    """

    summary: str = ""
    lessons_learned: list[str] = field(default_factory=list)
    improvements_for_tomorrow: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.summary
            and not self.lessons_learned
            and not self.improvements_for_tomorrow
            and not self.themes
        )

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "lessons_learned": list(self.lessons_learned),
            "improvements_for_tomorrow": list(self.improvements_for_tomorrow),
            "themes": list(self.themes),
        }


# Match a JSON object that may be wrapped in ```json … ``` fences or
# preceded by prose — defensive against model output that ignored the
# "no preamble, no markdown fence" instruction.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_payload(text: str) -> str:
    """Return the inner JSON text from possibly-fenced/prefixed output."""
    if not text:
        return ""
    fence = _FENCE_RE.search(text)
    candidate = fence.group(1) if fence else text
    obj = _JSON_OBJECT_RE.search(candidate)
    return obj.group(0) if obj else ""


def _coerce_str_list(value: object, *, max_items: int = 5) -> list[str]:
    """Best-effort: accept list/tuple of strings, drop non-strings, cap length."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
        if len(out) >= max_items:
            break
    return out


def parse_conclusions(response_text: str) -> ReflectionConclusions:
    """Parse a Deriver-prompt response into typed conclusions.

    Tolerant: if the model wrapped JSON in a markdown fence, prefixed
    it with prose, or omitted fields, return whatever was extractable.
    Returns an empty :class:`ReflectionConclusions` on unparseable
    input rather than raising — the caller decides whether to
    fall back to free-form prose.
    """
    payload = _extract_json_payload(response_text)
    if not payload:
        return ReflectionConclusions()
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return ReflectionConclusions()
    if not isinstance(data, dict):
        return ReflectionConclusions()

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    return ReflectionConclusions(
        summary=summary.strip(),
        lessons_learned=_coerce_str_list(data.get("lessons_learned")),
        improvements_for_tomorrow=_coerce_str_list(
            data.get("improvements_for_tomorrow"),
        ),
        themes=_coerce_str_list(data.get("themes")),
    )


def build_deriver_prompt(day_so_far: str) -> str:
    """Render :data:`DERIVER_PROMPT` with the chronicle excerpt substituted."""
    return DERIVER_PROMPT.format(day_so_far=day_so_far or "(empty)")


__all__ = [
    "DERIVER_PROMPT",
    "ReflectionConclusions",
    "build_deriver_prompt",
    "parse_conclusions",
]
