"""v4.63 (ADR 0082) — task splitter.

The 2026-05-19 escalation postmortem named two anti-patterns: long
research tasks bundled as one INBOX item, and multi-section
deliverables that force the agent to sequence 4+ tool types in one
cycle. v4.56 (ADR 0075) added a research-task tier floor — fixes
the tier choice. This module fixes the SHAPE.

Two surfaces:

  1. A pure heuristic ``is_splittable_shape(task_text)`` that the
     operator (or future ASSESS-phase hook) can use to decide
     whether to invoke the model-driven splitter at all.

  2. A model-driven ``split_task(task_text, provider)`` that asks
     a sonnet-tier model to propose 2-6 independent sub-tasks,
     returns ``list[str]``.

Auto-integration into the loop is OPT-IN and currently deferred —
operators preview the split via ``chimera split <task_text>`` and
manually rewrite INBOX. Once the heuristic is validated, a future
ADR can promote it to default-on with mutation-queue gating.

Cost: a sonnet-tier splitter call is ~$0.003 (2K input + 1K output
at deepseek-v4-pro rates, post-ADR-0072 ladder inversion). Cheap
enough that the per-task budget (ADR 0079) absorbs it without
operator-visible impact, as long as the splitter is called AT MOST
ONCE per task lifetime.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Heuristic patterns. Each one captures a multi-section / multi-deliverable
# / "for each X" shape that historically causes haiku to hit max_rounds.
_NUMBERED_SECTIONS_RE = re.compile(
    r"\(\s*[1-9]\s*\)[^(]+\(\s*[2-9]\s*\)",
    re.DOTALL,
)
_MULTI_SECTION_RE = re.compile(
    r"\bfour\s+sections?\b|\bthree\s+sections?\b|\bmultiple\s+sections?\b"
    r"|\beach\s+section\b|\bN\s+sections?\b",
    re.IGNORECASE,
)
_FOR_EACH_RE = re.compile(
    r"\bfor\s+each\s+(of\s+)?(the\s+)?\w+",
    re.IGNORECASE,
)
_MULTI_ARTIFACT_RE = re.compile(
    r"`((?:state|mind)/[A-Za-z0-9_./-]+)`"
)
_SPAWN_N_RE = re.compile(
    r"\bspawn\s+(\d+)\s+(?:sub-?agents?)\b",
    re.IGNORECASE,
)
# "spawn (a/the) sub-agent" + "for each" anywhere → implicit fanout.
# The 2026-05-19 dashboard-honesty-audit task used this exact shape
# ("for each widget … spawn a sub-agent") and burned 5 cycles.
_FANOUT_SHAPE_RE = re.compile(
    r"(for\s+each.*?(spawn|sub-?agent)|"
    r"(spawn|sub-?agent).*?for\s+each)",
    re.IGNORECASE | re.DOTALL,
)
_MULTI_DELIVERABLE_KEYWORDS = (
    "and write",
    "and append",
    "and queue",
    "then compile",
    "then synthesize",
    "then synthesise",
    "and critique",
)


@dataclass
class SplitSignal:
    """Result of the heuristic. ``confidence`` is 0–1; ≥ 0.5 → splittable."""

    splittable: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)


def is_splittable_shape(task_text: str) -> SplitSignal:
    """Pure heuristic — no model call, no DB read.

    The thresholds are tuned against the 2026-05-19 postmortem
    cases: the dashboard-honesty-audit task (14 sub-agents) and the
    4-section research task. Both trigger ≥ 2 patterns.
    """
    if not task_text or not task_text.strip():
        return SplitSignal(False, 0.0, [])

    reasons: list[str] = []
    score = 0.0

    # STRONG signals — each alone is enough to trigger (≥ 0.5).
    if _NUMBERED_SECTIONS_RE.search(task_text):
        score += 0.5
        reasons.append("contains '(1) … (2) …' numbered sections")
    if _MULTI_SECTION_RE.search(task_text):
        score += 0.5
        reasons.append("explicit multi-section phrasing")
    spawn_match = _SPAWN_N_RE.search(task_text)
    if spawn_match:
        n = int(spawn_match.group(1))
        if n >= 3:
            score += 0.5
            reasons.append(f"spawns {n} sub-agents (heavy fanout)")
        elif n >= 2:
            score += 0.3
            reasons.append(f"spawns {n} sub-agents")
    elif _FANOUT_SHAPE_RE.search(task_text):
        # 'for each X … spawn sub-agent' without a numeric count is
        # the 2026-05-19 dashboard-audit pattern: implicit per-item
        # fanout that's just as expensive as an explicit count.
        score += 0.5
        reasons.append("'for each … spawn sub-agent' implicit fanout shape")

    # MEDIUM signals — combine with another to trigger.
    artifacts = _MULTI_ARTIFACT_RE.findall(task_text)
    if len(artifacts) >= 3:
        score += 0.4
        reasons.append(f"{len(artifacts)} declared artifacts (multi-deliverable)")
    elif len(artifacts) >= 2:
        score += 0.1
        reasons.append(f"{len(artifacts)} declared artifacts")

    lower = task_text.lower()
    multi_deliv_hits = [k for k in _MULTI_DELIVERABLE_KEYWORDS if k in lower]
    if len(multi_deliv_hits) >= 2:
        score += 0.3
        reasons.append(f"multi-step deliverable phrasing: {multi_deliv_hits}")

    # SOFT signals.
    if _FOR_EACH_RE.search(task_text):
        score += 0.2
        reasons.append("'for each X' pattern (implies fanout)")
    # Long task text is a soft signal (more room to fit a fanout shape).
    if len(task_text) >= 1500:
        score += 0.1
        reasons.append(f"long task text ({len(task_text)} chars)")

    score = min(1.0, score)
    return SplitSignal(
        splittable=(score >= 0.5),
        confidence=round(score, 3),
        reasons=reasons,
    )


# ── model-driven split ─────────────────────────────────────────


SPLITTER_SYSTEM_PROMPT = """\
You split bundled multi-section / multi-deliverable INBOX tasks into
small INDEPENDENT sub-tasks the agent can run one per cycle.

Rules:
- Each sub-task must be self-contained — no shared state with siblings.
- Each sub-task must be < 800 characters.
- Each sub-task must name its own declared artifact path (state/* or mind/*).
- Prefer 2–6 sub-tasks; if the original isn't splittable, say so.
- Preserve the original's CONSTRAINTS (citation rules, tier hints, sub-agent
  models if specified) on every sub-task.

Output: JSON only, no prose. Shape:
  {"split": true, "subtasks": ["...", "...", "..."]}
  or
  {"split": false, "reason": "..."}
"""


def build_splitter_prompt(task_text: str) -> str:
    """User-message portion of the splitter call.

    Kept short so the operator can read the prompt verbatim from
    the test fixture.
    """
    return (
        "Task to evaluate for splitting:\n\n"
        f"---\n{task_text.strip()}\n---\n\n"
        "Respond with the JSON shape described in the system prompt."
    )


_JSON_BLOCK_RE = re.compile(
    r"\{[^{}]*\"split\"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
    re.DOTALL,
)


def parse_splitter_response(text: str) -> list[str]:
    """Extract ``subtasks`` from the model's reply.

    The model is asked for raw JSON, but defensively accept markdown
    code-fenced JSON too. Returns ``[]`` on parse failure or when the
    model says ``split: false``.
    """
    if not text:
        return []

    # Strip a markdown code fence if present.
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence + optional language tag.
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)

    # Try the whole reply first.
    candidates = [stripped]
    # Then any JSON-looking block embedded in prose.
    candidates += _JSON_BLOCK_RE.findall(text)

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if not data.get("split"):
            return []
        subs = data.get("subtasks")
        if not isinstance(subs, list):
            continue
        clean = [s.strip() for s in subs if isinstance(s, str) and s.strip()]
        return clean
    return []


async def split_task(
    task_text: str,
    *,
    provider,
    model_id: str,
    max_subtasks: int = 6,
) -> list[str]:
    """Call a model to propose sub-tasks. Returns [] if the model
    declines, the provider call fails, or parsing fails.

    The caller picks the provider — typically a sonnet-tier rung
    (deepseek-v4-pro post-v4.53). The CLI verb and any future
    ASSESS-phase hook both resolve the provider+model_id via
    ``chimera.providers.select_rung("sonnet")`` and pass them in.
    Keeping resolution out of this function keeps it test-friendly.
    """
    if not task_text or not task_text.strip():
        return []
    from ..providers import Message
    messages = [
        Message.system(SPLITTER_SYSTEM_PROMPT),
        Message.user(build_splitter_prompt(task_text)),
    ]
    try:
        response = await provider.complete_with_tools(
            messages=messages,
            model_id=model_id,
            tools=[],
            max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("split_task: provider call failed: %s", exc)
        return []

    # ChatResponse.text is the concatenated assistant reply. The
    # splitter prompt asks for JSON only; parse_splitter_response
    # is defensive about markdown fences and embedded JSON blocks.
    text = getattr(response, "text", "") or ""
    parsed = parse_splitter_response(text)
    return parsed[:max_subtasks]


__all__ = [
    "SplitSignal",
    "SPLITTER_SYSTEM_PROMPT",
    "build_splitter_prompt",
    "is_splittable_shape",
    "parse_splitter_response",
    "split_task",
]
