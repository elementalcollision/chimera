"""Semantic tool pre-filter — lexical v0 (ADR 0165).

The ACT executor hands the model *every* available tool schema on every
round (``registry.schemas()`` at ``core/act.py``). As the operator-
approved ``dynamic`` skills and the ``mcp-<peer>`` peer toolsets grow,
that catalog bloats — and tool-catalog bloat is a known accuracy /
token tax (vLLM Semantic Router blog, 2025-09-11: "Adding more tools …
can drastically reduce accuracy. The router must pre-filter tools and
keep catalogs tight"). See
``docs/research/semantic-routing-evaluation-2026-06-06.md``.

This module is the **zero-dependency first slice** of that evaluation's
recommended sequence: scope the per-task tool catalog by lexical
relevance. The ``core`` toolset is an always-on floor (the agent can
never be stranded without shell / code_exec / web / mind_search), so the
only tools ever pruned are the unbounded ``dynamic`` + ``mcp-*`` sets —
and only when the task text shows no lexical signal for them.

An embedding-backed upgrade slots into the same :func:`select_tool_schemas`
seam once ADR 0134 §"#6.b" picks the embedding model; until then the flag
defaults **off** and behaviour is byte-identical to ``registry.schemas()``.

Public surface:

  * :func:`tool_prefilter_enabled` — honours ``CHIMERA_TOOL_PREFILTER``.
  * :func:`select_tool_schemas` — the ACT call-site replacement.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from ..config import flag_enabled

logger = logging.getLogger(__name__)


# Toolsets that are ALWAYS exposed regardless of the task. ``core`` is the
# agent's foundational ability to act (shell, code_exec, http_fetch,
# web_search, mind_search, sub_agent, git_commit) — pruning it could strand
# a task with no way to make progress. Only the unbounded sets (``dynamic``
# skills, ``mcp-*`` peers) are ever filtered.
DEFAULT_ALWAYS_ON: frozenset[str] = frozenset({"core"})

# Drop tokens shorter than this — matches ``core.escalation._signature``'s
# 4-char floor, which already skips stop-words cheaply and deterministically.
_MIN_TOKEN_LEN = 4

# A small stop-word set on top of the length floor: common >=4-char words
# that carry no routing signal and would otherwise cause spurious matches
# between a tool description and an unrelated task.
_STOPWORDS: frozenset[str] = frozenset({
    "this", "that", "with", "from", "into", "your", "have", "will",
    "when", "then", "than", "them", "they", "what", "which", "would",
    "should", "could", "about", "after", "before", "tool", "tools",
    "call", "calls", "value", "values", "string", "object", "return",
    "returns", "given", "using", "make", "made", "does", "done",
})


def tool_prefilter_enabled() -> bool:
    """Honour ``CHIMERA_TOOL_PREFILTER`` (default: off, ADR 0165)."""
    return flag_enabled("CHIMERA_TOOL_PREFILTER")


def _tokens(text: str) -> set[str]:
    """Lower-cased alpha-numeric tokens >= 4 chars, minus stop-words."""
    return {
        t
        for t in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    }


def _tool_signal_tokens(entry: Any) -> set[str]:
    """Routing-signal tokens for one tool: its name, toolset, description,
    and (from the OpenAI-shaped schema) the function description + parameter
    names. Biased toward inclusion — better to occasionally keep an
    irrelevant tool than to prune one the task needed.
    """
    parts: list[str] = [
        getattr(entry, "name", "") or "",
        getattr(entry, "toolset", "") or "",
        getattr(entry, "description", "") or "",
    ]
    schema = getattr(entry, "schema", None) or {}
    fn = schema.get("function") if schema.get("type") == "function" else schema
    if isinstance(fn, dict):
        parts.append(str(fn.get("description", "")))
        params = (fn.get("parameters") or {}).get("properties") or {}
        if isinstance(params, dict):
            parts.extend(params.keys())
    return _tokens(" ".join(parts))


def _is_relevant(entry: Any, task_tokens: set[str]) -> bool:
    """A non-floor tool is relevant when its signal tokens overlap the
    task's tokens at all. Empty task tokens are handled by the caller
    (no pruning), so here a non-overlap is a confident prune.
    """
    return bool(_tool_signal_tokens(entry) & task_tokens)


def select_tool_schemas(
    registry: Any,
    task_text: str,
    *,
    always_on_toolsets: frozenset[str] = DEFAULT_ALWAYS_ON,
) -> list[dict[str, Any]]:
    """Return the tool schemas to expose for ``task_text``.

    Flag **off** (default): byte-identical to ``registry.schemas()`` — the
    full available catalog, same order. Flag **on**: the available catalog
    pruned to ``always_on_toolsets`` plus any tool whose signal tokens
    overlap the task.

    Safety rails:
      * The ``core`` floor (``always_on_toolsets``) is never pruned.
      * An empty / token-less task returns the full available catalog —
        we never strand a task on a parse miss.
      * Availability is honoured exactly as ``registry.schemas()`` does
        (unavailable tools are excluded in both paths).
    """
    if not tool_prefilter_enabled():
        return registry.schemas()

    task_tokens = _tokens(task_text)
    if not task_tokens:
        # No signal to route on — fall back to the full catalog.
        return registry.schemas()

    selected: list[dict[str, Any]] = []
    pruned = 0
    for name in registry.names():
        entry = registry.get(name)
        if entry is None:
            continue
        if not registry.is_available(name):
            continue  # mirror registry.schemas() availability gate
        if entry.toolset in always_on_toolsets or _is_relevant(entry, task_tokens):
            selected.append(entry.schema)
        else:
            pruned += 1

    if pruned:
        logger.debug(
            "tool_prefilter: exposed %d tool(s), pruned %d non-floor "
            "tool(s) with no lexical signal for the task",
            len(selected), pruned,
        )
    return selected


__all__ = [
    "DEFAULT_ALWAYS_ON",
    "select_tool_schemas",
    "tool_prefilter_enabled",
]
