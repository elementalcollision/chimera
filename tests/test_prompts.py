"""Tests for the adaptability prompt layer (hardware, history, voice)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import open_and_init, record_api_call
from chimera.prompts import (
    base_voice,
    build_system_prompt,
    probe_hardware,
    recent_history,
)


# ── voice ───────────────────────────────────────────────────


def test_voice_includes_chimera_identity():
    v = base_voice()
    assert "Chimera" in v
    assert "first person" in v.lower() or "first-person" in v.lower()
    # Anti-flattery rules referenced.
    assert "great question" in v.lower()


# ── hardware ────────────────────────────────────────────────


def test_hardware_probe_returns_sane_values():
    hw = probe_hardware()
    assert hw.cpu_count >= 1
    assert hw.platform  # non-empty
    line = hw.render()
    assert "CPU" in line
    assert "env:" in line


def test_hardware_render_handles_missing_memory(monkeypatch):
    """If we can't read mem, render shows '?' instead of crashing."""
    monkeypatch.setattr("chimera.prompts.hardware._mem_total_bytes", lambda: None)
    hw = probe_hardware()
    assert "?" in hw.render()


def test_hardware_env_keys_filtered_to_relevant_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("CHIMERA_MCP_SERVERS", raising=False)
    hw = probe_hardware()
    assert "ANTHROPIC_API_KEY" in hw.env_keys_present
    assert "OPENROUTER_API_KEY" not in hw.env_keys_present


# ── history ─────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_history_empty_renders_friendly(db):
    stats = recent_history(db, current_cycle=1, last_n_cycles=3)
    assert stats.total_calls == 0
    assert "none yet" in stats.render()


def test_history_aggregates_finish_and_model(db):
    record_api_call(
        db,
        cycle=1,
        provider="openrouter",
        model_id="deepseek/x",
        output_tokens=10,
        finish_reason="stop",
        latency_ms=100,
    )
    record_api_call(
        db,
        cycle=1,
        provider="openrouter",
        model_id="deepseek/x",
        output_tokens=20,
        finish_reason="tool_use",
        latency_ms=200,
    )
    record_api_call(
        db,
        cycle=2,
        provider="anthropic",
        model_id="claude-haiku",
        output_tokens=5,
        finish_reason="stop",
        latency_ms=50,
    )
    stats = recent_history(db, current_cycle=3, last_n_cycles=3)
    assert stats.total_calls == 3
    assert stats.by_finish == {"stop": 2, "tool_use": 1}
    rendered = stats.render()
    assert "calls=3" in rendered
    assert "deepseek/x" in rendered
    assert "claude-haiku" in rendered


def test_history_respects_cycle_window(db):
    record_api_call(
        db, cycle=1, provider="p", model_id="m", finish_reason="stop"
    )
    record_api_call(
        db, cycle=10, provider="p", model_id="m", finish_reason="stop"
    )
    # Window only covers cycle 9 (current=10, last_n=2 → cutoff=8 to 10 exclusive).
    stats = recent_history(db, current_cycle=10, last_n_cycles=2)
    assert stats.total_calls == 0  # cycle 1 too old, cycle 10 is current (excluded)


# ── build_system_prompt ─────────────────────────────────────


def test_build_system_prompt_includes_all_sections(db):
    record_api_call(db, cycle=1, provider="p", model_id="m", finish_reason="stop")
    prompt = build_system_prompt(db, cycle=2, extra="Task-specific extra.")
    assert "Chimera" in prompt
    assert "runtime:" in prompt
    assert "history" in prompt
    assert "Task-specific extra." in prompt


def test_build_system_prompt_without_extra(db):
    prompt = build_system_prompt(db, cycle=1)
    assert "Chimera" in prompt
    assert "runtime:" in prompt
