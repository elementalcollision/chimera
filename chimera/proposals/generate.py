"""Task-proposal extraction from a fenced ``tasks`` JSON block.

Per pillar-creativity.md Pattern 1 — Reggio's ``MAX_PROPOSED_TASKS_PER_PLAN = 3``
bound. Anything beyond that is dropped (not silently grown into more cycles).

The shape we ask the model for:

.. code-block:: text

    ```tasks
    [
      {"text": "Append a lesson to mind/LESSONS.md about ...",
       "rationale": "We learned X this cycle",
       "tool_hint": "shell"},
      ...
    ]
    ```

``rationale`` and ``tool_hint`` are optional. Unknown keys are ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

MAX_PROPOSED_TASKS_PER_PLAN: int = 3

_FENCE_RE = re.compile(r"```tasks\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ProposedTask:
    text: str
    rationale: str | None = None
    tool_hint: str | None = None


def extract_proposals(llm_text: str) -> list[ProposedTask]:
    """Parse 0..N ``tasks`` blocks; flatten; cap at :data:`MAX_PROPOSED_TASKS_PER_PLAN`.

    On malformed JSON: returns ``[]`` rather than raising. The PLAN phase
    should treat parse failures as "no new proposals" — the next cycle
    gets another chance.
    """
    out: list[ProposedTask] = []
    for match in _FENCE_RE.finditer(llm_text):
        payload = match.group(1).strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            out.append(
                ProposedTask(
                    text=text.strip(),
                    rationale=(item.get("rationale") or None) or None,
                    tool_hint=(item.get("tool_hint") or None) or None,
                )
            )
            if len(out) >= MAX_PROPOSED_TASKS_PER_PLAN:
                return out
    return out


PLAN_PROMPT_TEMPLATE = """You are the strategic planning component of Chimera, a tools-capable multi-LLM agent.

Current cycle: {cycle}
Open tasks in INBOX:
{open_tasks}

Recent activity summary (last few cycles):
{recent_summary}

Generate 0 to {max_n} NEW tasks that meaningfully move Chimera's work forward.
Each task must be:
- A single concrete imperative (one verb, one outcome).
- Self-contained — no references to earlier conversations the next reader can't see.
- Useful to the human operator who reads the INBOX.

NEVER duplicate or rephrase a task already in the INBOX.
If there is nothing worth proposing this cycle, return an empty array.

Respond in EXACTLY this format, with no prose before or after:

```tasks
[
  {{"text": "concrete imperative here", "rationale": "one-sentence why"}}
]
```
"""


def build_plan_prompt(
    *,
    cycle: int,
    open_tasks: list[str],
    recent_summary: str,
    max_n: int = MAX_PROPOSED_TASKS_PER_PLAN,
) -> str:
    if open_tasks:
        rendered = "\n".join(f"  - {t}" for t in open_tasks)
    else:
        rendered = "  (none)"
    return PLAN_PROMPT_TEMPLATE.format(
        cycle=cycle,
        open_tasks=rendered,
        recent_summary=recent_summary or "(no prior activity)",
        max_n=max_n,
    )
