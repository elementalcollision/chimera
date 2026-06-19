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
  * :func:`tool_schema_tokens` — stable token estimate for a schema list.
  * :func:`prefilter_savings` — flag-independent 0184 cost evidence.
"""

from __future__ import annotations

import json
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
    return _prefiltered_schemas(
        registry, task_text, always_on_toolsets=always_on_toolsets
    )


def _prefiltered_schemas(
    registry: Any,
    task_text: str,
    *,
    always_on_toolsets: frozenset[str] = DEFAULT_ALWAYS_ON,
) -> list[dict[str, Any]]:
    """The pruning core, **independent of the flag**.

    This is the exact relevance computation the live prefilter performs
    once ``CHIMERA_TOOL_PREFILTER`` is on: an empty / token-less task
    returns the full available catalog, otherwise the catalog pruned to
    ``always_on_toolsets`` plus any lexically-relevant tool. Factored out
    so :func:`select_tool_schemas` (flag-gated) and
    :func:`prefilter_savings` (flag-independent measurement) share one
    implementation — the measured prune can never drift from the live one.
    """
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


# Bytes-per-token divisor for the deterministic estimate. Tool schemas are
# dense JSON (field names, type keywords, nested braces), so the commonly
# cited "~4 chars per token" English heuristic is a stable, conservative
# proxy here — it needs no tokenizer/model dependency and never varies
# across machines, which is exactly what the ADR 0184 cost evidence needs.
_CHARS_PER_TOKEN = 4


def tool_schema_tokens(schemas: list[dict[str, Any]]) -> int:
    """Deterministic, offline token estimate for a list of tool schemas.

    Serialises ``schemas`` to compact JSON (``stdlib json`` only, no
    whitespace) and divides the character count by ``_CHARS_PER_TOKEN``
    (the ~4-chars-per-token heuristic). This is a *stable proxy*, not an
    exact tokenizer count: the goal is a reproducible, model-independent
    number so two schema lists can be compared apples-to-apples. The same
    serialisation + divisor is applied to both sides of a savings
    computation, so any heuristic bias cancels in the difference.

    Returns ``0`` for an empty list (``json.dumps([]) == "[]"`` → ``2 //
    4 == 0``).
    """
    blob = json.dumps(schemas, separators=(",", ":"))
    return len(blob) // _CHARS_PER_TOKEN


def prefilter_savings(
    task_text: str,
    registry: Any = None,
    *,
    context: Any = None,
) -> dict[str, int]:
    """Deterministic, offline tool-prefilter cost evidence (ADR 0184).

    Measures how many tool-definition input tokens the
    ``CHIMERA_TOOL_PREFILTER`` lever (ADR 0165) would save for one task,
    **independently of whether the flag is currently on**. The "full"
    side is the unpruned catalog (``registry.schemas()``); the "pruned"
    side is computed by the *exact same* relevance code the live
    prefilter runs (:func:`_prefiltered_schemas`), so the measurement can
    never drift from production behaviour. No soak, no API, no env
    mutation.

    ``registry`` defaults to the process-global default registry.
    ``context`` is accepted for forward-compatibility with a future
    embedding-backed selector seam (ADR 0134 §"#6.b") and is unused by the
    lexical v0 path.

    Returns a dict with::

        full_tokens   pruned_tokens   saved_tokens
        full_count    pruned_count

    where ``saved_tokens == full_tokens - pruned_tokens`` and
    ``pruned_count <= full_count``. On a token-less / empty task the
    pruned set equals the full catalog, so ``saved_tokens == 0`` and
    ``pruned_count == full_count``.
    """
    del context  # reserved; lexical v0 routes on task_text only
    if registry is None:
        from .registry import default_registry

        registry = default_registry()

    full = registry.schemas()
    pruned = _prefiltered_schemas(registry, task_text)

    full_tokens = tool_schema_tokens(full)
    pruned_tokens = tool_schema_tokens(pruned)
    return {
        "full_tokens": full_tokens,
        "pruned_tokens": pruned_tokens,
        "saved_tokens": full_tokens - pruned_tokens,
        "full_count": len(full),
        "pruned_count": len(pruned),
    }


__all__ = [
    "DEFAULT_ALWAYS_ON",
    "prefilter_savings",
    "select_tool_schemas",
    "tool_prefilter_enabled",
    "tool_schema_tokens",
]
