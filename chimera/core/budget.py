"""Adaptive per-task budgets for ACT (v4.5, ADR 0028).

The static ``max_rounds`` cap was the right primitive at v3.11 but
penalised compound multi-tool / multi-artifact tasks while leaving
headroom unused for simpler ones. v4.5 scales the budget by task
shape — declared artifacts and named tools — within a global ceiling.

The functions here are pure; ACT calls :func:`dynamic_max_rounds` per
task at the start of its loop.
"""

from __future__ import annotations

import re

# Keywords that strongly suggest a distinct tool-call step. Conservative
# — we only count keywords the task author would naturally use.
_TOOL_KEYWORDS = (
    "web_search",
    "http_fetch",
    "code_exec",
    "shell",
    "spawn_sub_agent",
    "sub-agent",
    "sub agent",
)


def _count_artifacts(task_text: str) -> int:
    from .act import expected_artifacts
    return len(expected_artifacts(task_text))


def _count_tool_keywords(task_text: str) -> int:
    lower = task_text.lower()
    return sum(1 for kw in _TOOL_KEYWORDS if kw in lower)


def dynamic_max_rounds(
    task_text: str,
    *,
    base: int = 12,
    per_artifact: int = 4,
    per_tool: int = 2,
    cap: int = 32,
) -> int:
    """Compute a per-task round budget.

    ``base`` is the floor for any task. ``per_artifact`` adds room for
    each declared output file; ``per_tool`` adds room for each named
    tool keyword. ``cap`` is the hard ceiling — long compound tasks
    can't escape ACT entirely.
    """
    if base < 1:
        base = 1
    if cap < base:
        cap = base
    artifacts = _count_artifacts(task_text)
    tools = _count_tool_keywords(task_text)
    budget = base + per_artifact * artifacts + per_tool * tools
    return max(base, min(cap, budget))
