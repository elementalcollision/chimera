"""Tests for v4.9 named-rung selection + skill-assembly journal."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.providers import (
    HAIKU,
    OPUS,
    SONNET,
    resolve_rung,
)
from chimera.skills import (
    AttemptOutcome,
    LadderResult,
    ValidationResult,
    list_assemblies,
    record_assembly,
)
from chimera.skills.assembly import AssembledSkill
from chimera.skills.spec import SkillSpec


# ── named-rung selection ────────────────────────────────────


def test_resolve_rung_tier_name_returns_cheapest():
    assert resolve_rung("haiku").config is not None
    # haiku ladder's cheapest is the first OpenRouter rung; the alias
    # for HAIKU itself is the anthropic safety net.
    assert resolve_rung("haiku").config.model_id != HAIKU.model_id


def test_resolve_rung_per_rung_alias_short_form():
    """Per-rung alias drops the provider prefix."""
    rung = resolve_rung("gpt-5.1-codex-max")
    assert rung.config.openrouter_model_id == "openai/gpt-5.1-codex-max"

    rung = resolve_rung("gemini-3.1-pro-preview")
    assert rung.config.openrouter_model_id == "google/gemini-3.1-pro-preview"

    rung = resolve_rung("deepseek-v4-pro")
    assert "deepseek-v4-pro" in rung.config.openrouter_model_id


def test_resolve_rung_full_model_id_works_too():
    rung = resolve_rung("claude-opus-4-7")
    assert rung.config is OPUS

    rung = resolve_rung("openai/gpt-5.1-codex-max")
    assert rung.config.openrouter_model_id == "openai/gpt-5.1-codex-max"


def test_resolve_rung_unknown_raises():
    with pytest.raises(ValueError, match="unknown rung"):
        resolve_rung("not-a-real-model-name")


# ── assembly journal ────────────────────────────────────────


def _spec() -> SkillSpec:
    return SkillSpec(name="journal_demo", description="d", brief="b")


def _result(winning_tier: str | None, attempts: list[AttemptOutcome]) -> LadderResult:
    return LadderResult(
        assembled=AssembledSkill(spec=_spec(), ok=True),
        validation=ValidationResult(ok=winning_tier is not None, score=1.0 if winning_tier else 0.0, passed=3 if winning_tier else 0, total=3),
        attempts=attempts,
        winning_tier=winning_tier,
    )


def test_record_assembly_round_trip(tmp_path: Path):
    log = tmp_path / "assembly.jsonl"
    attempts = [
        AttemptOutcome(
            tier="sonnet", assembled_ok=True, validation_score=0.33,
            validation_ok=False, failure_reason="0.33 < 0.6",
            revised=True, revised_score=0.33,
            witnesses=("sonnet", "opus"), winning_witness=None,
        )
    ]
    record_assembly(
        mutation_id=42, skill_name="demo",
        result=_result(None, attempts), path=log,
    )
    rows = list_assemblies(path=log)
    assert len(rows) == 1
    assert rows[0]["mutation_id"] == 42
    assert rows[0]["winning_tier"] is None
    assert rows[0]["attempts"][0]["witnesses"] == ["sonnet", "opus"]
    assert rows[0]["attempts"][0]["revised"] is True


def test_record_assembly_with_winner(tmp_path: Path):
    log = tmp_path / "assembly.jsonl"
    attempts = [
        AttemptOutcome(
            tier="opus", assembled_ok=True, validation_score=0.0,
            validation_ok=False, failure_reason=None,
            revised=True, revised_score=1.0,
            witnesses=("sonnet", "opus"), winning_witness="opus",
        )
    ]
    record_assembly(
        mutation_id=43, skill_name="winner_demo",
        result=_result("opus", attempts), path=log,
    )
    rows = list_assemblies(path=log)
    assert rows[0]["winning_tier"] == "opus"
    assert rows[0]["attempts"][0]["winning_witness"] == "opus"


def test_list_assemblies_limit(tmp_path: Path):
    log = tmp_path / "assembly.jsonl"
    for i in range(5):
        attempts = [
            AttemptOutcome(
                tier="sonnet", assembled_ok=True, validation_score=0.0,
                validation_ok=False, failure_reason="x",
            )
        ]
        record_assembly(
            mutation_id=i, skill_name=f"d{i}",
            result=_result(None, attempts), path=log,
        )
    rows = list_assemblies(path=log, limit=2)
    assert [r["mutation_id"] for r in rows] == [3, 4]
