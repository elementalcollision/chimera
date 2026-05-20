"""v4.70 (ADR 0089) — signal-density gates for the engines."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.engine_gates import (
    GateDecision,
    curiosity_gate,
    discovery_gate,
    gates_enabled,
    reflection_gate,
)
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── master switch ─────────────────────────────────────────────


def test_gates_enabled_default_on(monkeypatch):
    monkeypatch.delenv("CHIMERA_ENGINE_GATES_ENABLED", raising=False)
    assert gates_enabled() is True


def test_gates_enabled_off(monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINE_GATES_ENABLED", "0")
    assert gates_enabled() is False


# ── discovery_gate ────────────────────────────────────────────


def test_discovery_gate_skips_on_empty_db(db, monkeypatch):
    monkeypatch.delenv("CHIMERA_DISCOVERY_MIN_API_CALLS", raising=False)
    decision = discovery_gate(db, cycle=10)
    assert decision.allow is False
    assert "cold-start" in decision.reason


def test_discovery_gate_allows_when_threshold_met(db, monkeypatch):
    monkeypatch.delenv("CHIMERA_DISCOVERY_MIN_API_CALLS", raising=False)
    # Lookback=5, cycle=12 → cutoff=7. Seed cycles 8-12 → 5 rows in window,
    # meets the default threshold of 5.
    for cycle in (8, 9, 10, 11, 12):
        record_api_call(
            db, cycle=cycle, provider="openrouter",
            model_id="deepseek/deepseek-v4-flash",
            input_tokens=100, output_tokens=50,
        )
    db.commit()
    decision = discovery_gate(db, cycle=12)
    assert decision.allow is True, decision.reason


def test_discovery_gate_env_threshold(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_DISCOVERY_MIN_API_CALLS", "10")
    # 5 calls < 10 → skip.
    for cycle in (1, 2, 3, 4, 5):
        record_api_call(
            db, cycle=cycle, provider="openrouter",
            model_id="deepseek/deepseek-v4-flash",
            input_tokens=100, output_tokens=50,
        )
    db.commit()
    decision = discovery_gate(db, cycle=6)
    assert decision.allow is False
    assert "< 10" in decision.reason


def test_discovery_gate_disabled_when_threshold_zero(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_DISCOVERY_MIN_API_CALLS", "0")
    decision = discovery_gate(db, cycle=1)
    assert decision.allow is True


def test_discovery_gate_master_switch_off(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINE_GATES_ENABLED", "0")
    # Even with empty DB, master switch off → allow.
    decision = discovery_gate(db, cycle=10)
    assert decision.allow is True


# ── curiosity_gate ────────────────────────────────────────────


def _chronicle(today: str, sections: dict[str, str]) -> str:
    body = f"# Chimera Chronicle\n\n## {today}\n\n"
    for name, content in sections.items():
        body += f"### {name}\n\n{content}\n\n"
    return body


def test_curiosity_gate_skips_when_no_chronicle(monkeypatch):
    decision = curiosity_gate(None, today_iso="2026-05-20")
    assert decision.allow is False
    assert "no chronicle" in decision.reason.lower()


def test_curiosity_gate_skips_when_no_today_section(monkeypatch):
    text = "# Chronicle\n\n## 2026-05-15\n\n### Morning Discovery\n\n- alpha\n- beta\n"
    decision = curiosity_gate(text, today_iso="2026-05-20")
    assert decision.allow is False
    assert "no chronicle section for today" in decision.reason.lower()


def test_curiosity_gate_skips_when_no_discovery_section(monkeypatch):
    text = _chronicle("2026-05-20", {"Evening Reflection": "wrote some code"})
    decision = curiosity_gate(text, today_iso="2026-05-20")
    assert decision.allow is False
    assert "no Morning Discovery" in decision.reason


def test_curiosity_gate_skips_on_cold_start_marker(monkeypatch):
    text = _chronicle(
        "2026-05-20",
        {"Morning Discovery":
         "- Fresh session initiation; no prior history to analyze.\n"
         "- New engagement with seed verification.\n"},
    )
    decision = curiosity_gate(text, today_iso="2026-05-20")
    assert decision.allow is False
    assert "cold-start marker" in decision.reason


def test_curiosity_gate_skips_on_single_bullet(monkeypatch):
    text = _chronicle(
        "2026-05-20",
        {"Morning Discovery": "- One thin observation only.\n"},
    )
    decision = curiosity_gate(text, today_iso="2026-05-20")
    assert decision.allow is False
    assert "only 1 bullet" in decision.reason


def test_curiosity_gate_allows_on_substantive_discovery(monkeypatch):
    text = _chronicle(
        "2026-05-20",
        {"Morning Discovery":
         "- Worked on engine telemetry refactor.\n"
         "- Closed three skill_proposal mutations.\n"
         "- Investigated dead-entity query bug.\n"},
    )
    decision = curiosity_gate(text, today_iso="2026-05-20")
    assert decision.allow is True
    assert "3 bullets" in decision.reason


def test_curiosity_gate_master_switch_off(monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINE_GATES_ENABLED", "0")
    decision = curiosity_gate(None)
    assert decision.allow is True


def test_curiosity_gate_disable_discovery_prereq(monkeypatch):
    monkeypatch.setenv("CHIMERA_CURIOSITY_REQUIRE_DISCOVERY", "0")
    decision = curiosity_gate(None)
    assert decision.allow is True


# ── reflection_gate ───────────────────────────────────────────


def test_reflection_gate_skips_on_quiet_day(db, monkeypatch):
    monkeypatch.delenv("CHIMERA_REFLECTION_MIN_CYCLES", raising=False)
    # Empty DB → 0 cycles today → skip (default threshold = 3).
    decision = reflection_gate(db, cycle=10)
    assert decision.allow is False
    assert "0 cycle" in decision.reason


def test_reflection_gate_allows_when_threshold_met(db, monkeypatch):
    monkeypatch.delenv("CHIMERA_REFLECTION_MIN_CYCLES", raising=False)
    # 3 distinct cycles with api_calls today (created_at default = now).
    for cycle in (1, 2, 3):
        record_api_call(
            db, cycle=cycle, provider="openrouter",
            model_id="deepseek/deepseek-v4-flash",
            input_tokens=100, output_tokens=50,
        )
    db.commit()
    decision = reflection_gate(db, cycle=4)
    assert decision.allow is True


def test_reflection_gate_disabled_when_threshold_zero(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_REFLECTION_MIN_CYCLES", "0")
    decision = reflection_gate(db, cycle=1)
    assert decision.allow is True


def test_reflection_gate_master_switch_off(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINE_GATES_ENABLED", "0")
    decision = reflection_gate(db, cycle=1)
    assert decision.allow is True


# ── overnight-burn-context regression ─────────────────────────


def test_overnight_burn_curiosity_would_skip(monkeypatch):
    """Reproduce the 2026-05-19 cold-start chronicle and verify the
    gate would skip — proving the post-mortem's biggest behavioural
    fix works as designed."""
    text = _chronicle(
        "2026-05-19",
        {"Morning Discovery":
         "- Fresh session initiation; no prior history to analyze "
         "for patterns or repetition.\n"
         "- New engagement with a seed verification task, indicating "
         "foundational system setup or identity check.\n"
         "- No notable failures or successes yet; session is at "
         "earliest stage of activity.\n"},
    )
    decision = curiosity_gate(text, today_iso="2026-05-19")
    assert decision.allow is False
    assert "cold-start marker" in decision.reason
