"""Tests for the semantic tool pre-filter (ADR 0165)."""

from __future__ import annotations

import pytest

from chimera.tools import ToolRegistry, select_tool_schemas, tool_prefilter_enabled


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
    """A registry with a core floor + one dynamic skill + one mcp peer tool."""
    reg = ToolRegistry()
    reg.register(
        name="shell", toolset="core",
        schema=_schema("shell", description="run a subprocess command"),
        handler=_trivial_handler,
    )
    reg.register(
        name="code_exec", toolset="core",
        schema=_schema("code_exec", description="execute python code"),
        handler=_trivial_handler,
    )
    reg.register(
        name="reverse_string", toolset="dynamic",
        schema=_schema("reverse_string", description="reverse the characters in a string"),
        handler=_trivial_handler,
    )
    reg.register(
        name="mcp-weather-forecast", toolset="mcp-weather",
        schema=_schema(
            "mcp-weather-forecast",
            description="fetch the weather forecast for a location",
            params={"location": {"type": "string"}},
        ),
        handler=_trivial_handler,
    )
    return reg


def _names(schemas: list[dict]) -> set[str]:
    return {s["function"]["name"] for s in schemas}


# ── flag OFF: identical to registry.schemas() ──────────────────────


def test_flag_explicit_disable_returns_full_catalog(monkeypatch):
    # ADR 0184: default-ON now, so the full-catalog (no-prune) behaviour requires
    # an EXPLICIT opt-out (CHIMERA_TOOL_PREFILTER=0).
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "0")
    reg = _registry()
    assert not tool_prefilter_enabled()
    got = select_tool_schemas(reg, "anything at all here")
    assert got == reg.schemas()
    assert _names(got) == {"shell", "code_exec", "reverse_string", "mcp-weather-forecast"}


def test_flag_on_by_default(monkeypatch):
    # ADR 0184 graduation: unset → ON (registry default "1").
    monkeypatch.delenv("CHIMERA_TOOL_PREFILTER", raising=False)
    assert tool_prefilter_enabled()


# ── flag ON ────────────────────────────────────────────────────────


def test_flag_on_keeps_core_floor_always(monkeypatch):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    reg = _registry()
    # Task unrelated to either non-core tool — core still present.
    got = _names(select_tool_schemas(reg, "summarise the quarterly budget figures"))
    assert {"shell", "code_exec"} <= got
    # Both non-floor tools pruned (no lexical signal).
    assert "reverse_string" not in got
    assert "mcp-weather-forecast" not in got


def test_flag_on_includes_lexically_relevant_dynamic_tool(monkeypatch):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    reg = _registry()
    got = _names(select_tool_schemas(reg, "please reverse this string for me"))
    assert "reverse_string" in got           # 'reverse' + 'string' match
    assert "mcp-weather-forecast" not in got  # still no weather signal


def test_flag_on_includes_relevant_mcp_tool(monkeypatch):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    reg = _registry()
    got = _names(select_tool_schemas(reg, "what is the weather forecast tomorrow"))
    assert "mcp-weather-forecast" in got
    assert "reverse_string" not in got


def test_flag_on_empty_task_returns_full_catalog(monkeypatch):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    reg = _registry()
    # No routable tokens → never strand the task; expose everything.
    assert select_tool_schemas(reg, "") == reg.schemas()
    assert select_tool_schemas(reg, "a in to of") == reg.schemas()


def test_flag_on_respects_availability_gate(monkeypatch):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", "1")
    reg = _registry()
    reg.register(
        name="offline_skill", toolset="dynamic",
        schema=_schema("offline_skill", description="reverse a string offline"),
        handler=_trivial_handler,
        check_fn=lambda: False,  # unavailable
        override=False,
    )
    got = _names(select_tool_schemas(reg, "reverse the string"))
    # Relevant by tokens, but unavailable → excluded, just like schemas().
    assert "offline_skill" not in got
    assert "reverse_string" in got


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nope", False),
])
def test_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", val)
    assert tool_prefilter_enabled() is expected
