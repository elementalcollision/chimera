"""Tests for the ADR 0184 prefilter token-savings instrumentation.

These cover the deterministic, offline cost-evidence primitives added to
``chimera.tools.tool_selection``:

  * :func:`tool_schema_tokens` — stable token estimate for a schema list.
  * :func:`prefilter_savings` — flag-independent saved-token measurement.

The measurement must be independent of the live ``CHIMERA_TOOL_PREFILTER``
env, and the pruned set must be computed by the exact same relevance code
the live prefilter uses.
"""

from __future__ import annotations

import pytest

from chimera.tools import (
    ToolRegistry,
    default_registry,
    prefilter_savings,
    register_core_tools,
    tool_schema_tokens,
)


async def _trivial_handler(args, context):
    return "ok"


def _schema(name: str, *, description: str = "", params: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": params or {},
            },
        },
    }


def _registry() -> ToolRegistry:
    """A realistic registry: the real core floor (via ``register_core_tools``)
    plus a couple of non-floor ``dynamic`` / ``mcp-*`` tools the prefilter can
    prune. Using ``register_core_tools`` keeps this aligned with the real
    catalog the ACT loop advertises rather than a hand-rolled stand-in.
    """
    reg = ToolRegistry()
    register_core_tools(reg)
    reg.register(
        name="reverse_string",
        toolset="dynamic",
        schema=_schema(
            "reverse_string",
            description="reverse the characters in a string",
        ),
        handler=_trivial_handler,
    )
    reg.register(
        name="mcp-weather-forecast",
        toolset="mcp-weather",
        schema=_schema(
            "mcp-weather-forecast",
            description="fetch the weather forecast for a location",
            params={"location": {"type": "string"}},
        ),
        handler=_trivial_handler,
    )
    return reg


# ── (a) tool_schema_tokens ─────────────────────────────────────────


def test_tool_schema_tokens_empty_is_zero():
    assert tool_schema_tokens([]) == 0


def test_tool_schema_tokens_positive_and_monotone():
    one = [_schema("alpha", description="does the alpha thing")]
    two = one + [_schema("beta", description="does the beta thing")]
    three = two + [_schema("gamma", description="does the gamma thing")]

    t1 = tool_schema_tokens(one)
    t2 = tool_schema_tokens(two)
    t3 = tool_schema_tokens(three)

    # Positive for a non-empty list.
    assert t1 > 0
    # Strictly increases as more schemas are added.
    assert t1 < t2 < t3


def test_tool_schema_tokens_deterministic():
    schemas = [_schema("alpha", description="alpha thing"), _schema("beta")]
    assert tool_schema_tokens(schemas) == tool_schema_tokens(schemas)


# ── (b) prefilter_savings on a narrow task ─────────────────────────


def test_prefilter_savings_prunes_irrelevant_tools():
    reg = _registry()
    # 'reverse'/'string' match only the reverse_string dynamic tool; the
    # weather mcp tool (and any non-matching dynamic/mcp tools) get pruned.
    out = prefilter_savings("please reverse this string for me", reg)

    assert out["saved_tokens"] > 0
    assert out["pruned_count"] < out["full_count"]
    # saved_tokens is exactly the token delta between full and pruned.
    assert out["saved_tokens"] == out["full_tokens"] - out["pruned_tokens"]
    assert out["pruned_tokens"] < out["full_tokens"]
    # Pruning only ever removes tools, never adds.
    assert out["pruned_count"] >= 1


def test_prefilter_savings_is_flag_independent(monkeypatch):
    reg = _registry()
    task = "what is the weather forecast for tomorrow"

    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "0")
    off = prefilter_savings(task, reg)
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    on = prefilter_savings(task, reg)
    monkeypatch.delenv("CHIMERA_TOOL_PREFILTER", raising=False)
    unset = prefilter_savings(task, reg)

    # Measurement does not depend on the live flag.
    assert off == on == unset
    # The weather task prunes the reverse_string tool → real savings.
    assert off["saved_tokens"] > 0
    assert off["pruned_count"] < off["full_count"]


# ── (c) empty / token-less task → no savings ───────────────────────


@pytest.mark.parametrize("task", ["", "   ", "a in to of", "the and or"])
def test_prefilter_savings_tokenless_task_no_savings(task):
    reg = _registry()
    out = prefilter_savings(task, reg)

    assert out["saved_tokens"] == 0
    assert out["pruned_count"] == out["full_count"]
    assert out["full_tokens"] == out["pruned_tokens"]


# ── default registry path ──────────────────────────────────────────


def test_prefilter_savings_defaults_to_default_registry():
    register_core_tools()  # idempotent; ensures the global has the core floor
    out = prefilter_savings("reverse this string", registry=None)

    expected_full = len(default_registry().schemas())
    assert out["full_count"] == expected_full
    # Shape contract: all five integer fields present.
    assert set(out) == {
        "full_tokens",
        "pruned_tokens",
        "saved_tokens",
        "full_count",
        "pruned_count",
    }
    assert all(isinstance(v, int) for v in out.values())
