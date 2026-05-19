"""Tests for v4.8 cross-witness critique + expanded opus ladder (ADR 0031)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import open_and_init
from chimera.providers import OPUS, OPUS_LADDER
from chimera.skills import (
    AssembledSkill,
    SkillSpec,
    ValidationResult,
    assemble_with_escalation,
)
from chimera.skills.cross_critique import cross_critique


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _spec() -> SkillSpec:
    return SkillSpec(name="cw_demo", description="d", brief="b")


def _ok(text: str) -> AssembledSkill:
    return AssembledSkill(
        spec=_spec(),
        ok=True,
        schema={"function": {"name": "cw_demo"}},
        handler_code=text,
        samples=[{"input": {}, "expect": ""}],
        raw_text="",
    )


def test_opus_ladder_starts_with_anthropic_opus():
    """v4.8: Anthropic OPUS is the first rung after the reorder."""
    assert OPUS_LADDER[0].config is OPUS


def test_default_witnesses_span_three_providers():
    """v4.13: default witness pool draws from Anthropic + OpenAI + Google."""
    from inspect import signature
    sig = signature(assemble_with_escalation)
    default = sig.parameters["witnesses"].default
    assert default is not None
    names = list(default)
    assert "claude-opus-4-7" in names
    assert "gpt-5-pro" in names
    assert "gemini-3-pro" in names
    # Three distinct rungs from three distinct providers.
    from chimera.providers import resolve_rung
    providers = {resolve_rung(n).config.provider for n in names}
    assert len(providers) >= 2  # Anthropic vs OpenRouter at minimum


def test_opus_ladder_includes_openai_and_gemini():
    ids = [r.config.openrouter_model_id for r in OPUS_LADDER]
    assert any("openai/" in m for m in ids)
    assert any("google/" in m or "gemini" in m for m in ids)


# ── cross_critique ─────────────────────────────────────────


async def test_cross_critique_picks_highest_score(db, monkeypatch):
    async def fake_critique(spec, assembled, validation, *, providers, db, cycle, tier, max_tokens=2048):
        # sonnet returns a strong revision, opus a weaker one.
        return _ok("revised_" + tier)

    async def fake_validate(assembled):
        score_map = {"revised_sonnet": 1.0, "revised_opus": 0.5}
        score = score_map.get(assembled.handler_code, 0.0)
        return ValidationResult(
            ok=(score >= 0.6), score=score,
            passed=int(score * 3), total=3,
        )

    monkeypatch.setattr("chimera.skills.cross_critique.critique_and_revise", fake_critique)
    monkeypatch.setattr("chimera.skills.cross_critique.validate_skill", fake_validate)

    result = await cross_critique(
        _spec(),
        _ok("base"),
        ValidationResult(ok=False, score=0.0, passed=0, total=3),
        providers={}, db=db, cycle=1,
        witnesses=("sonnet", "opus"),
    )
    assert result.winning_witness == "sonnet"
    assert result.best_validation is not None
    assert result.best_validation.score == 1.0
    assert {w.tier for w in result.witnesses} == {"sonnet", "opus"}


async def test_cross_critique_ties_prefer_cheaper_witness(db, monkeypatch):
    """When witnesses tie on score, the earlier (cheaper) witness wins."""
    async def fake_critique(spec, assembled, validation, *, providers, db, cycle, tier, max_tokens=2048):
        return _ok("revised_" + tier)

    async def fake_validate(assembled):
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    monkeypatch.setattr("chimera.skills.cross_critique.critique_and_revise", fake_critique)
    monkeypatch.setattr("chimera.skills.cross_critique.validate_skill", fake_validate)

    result = await cross_critique(
        _spec(),
        _ok("base"),
        ValidationResult(ok=False, score=0.0, passed=0, total=3),
        providers={}, db=db, cycle=1,
        witnesses=("sonnet", "opus"),
    )
    assert result.winning_witness == "sonnet"


async def test_cross_critique_returns_none_when_all_witnesses_fail(db, monkeypatch):
    async def fake_critique(*a, **kw):
        return None  # no parseable revision

    monkeypatch.setattr("chimera.skills.cross_critique.critique_and_revise", fake_critique)

    result = await cross_critique(
        _spec(),
        _ok("base"),
        ValidationResult(ok=False, score=0.0, passed=0, total=3),
        providers={}, db=db, cycle=1,
        witnesses=("sonnet", "opus"),
    )
    assert result.winning_witness is None
    assert result.best_assembled is None
    assert all(not w.revised_ok for w in result.witnesses)


# ── ladder integration ─────────────────────────────────────


async def test_ladder_with_witnesses_returns_winning_witness(db, monkeypatch):
    """First tier's validation fails; cross-critique on (sonnet, opus)
    produces a passing revision via opus; ladder returns it with the
    witness recorded."""
    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        return _ok("first_" + tier)

    async def fake_validate(assembled):
        if assembled.handler_code.startswith("first_"):
            return ValidationResult(ok=False, score=0.0, passed=0, total=3)
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    async def fake_xc(spec, assembled, validation, *, providers, db, cycle, witnesses, max_tokens=2048):
        from chimera.skills.cross_critique import CrossCritiqueResult, WitnessOutcome
        return CrossCritiqueResult(
            best_assembled=_ok("revised_opus"),
            best_validation=ValidationResult(ok=True, score=1.0, passed=3, total=3),
            winning_witness="opus",
            witnesses=[
                WitnessOutcome(tier="sonnet", revised_ok=False, score=0.3, failure_reason="x"),
                WitnessOutcome(tier="opus", revised_ok=True, score=1.0, failure_reason=None),
            ],
        )

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)
    monkeypatch.setattr("chimera.skills.ladder.cross_critique", fake_xc)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet",), witnesses=("sonnet", "opus"),
    )
    assert result.winning_tier == "sonnet"
    assert result.attempts[0].witnesses == ("sonnet", "opus")
    assert result.attempts[0].winning_witness == "opus"
    assert result.attempts[0].revised_score == 1.0
