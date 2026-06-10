"""Tests for v4.6 assembler tier escalation (ADR 0029)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import open_and_init
from chimera.skills import (
    AssembledSkill,
    SkillSpec,
    ValidationResult,
    assemble_with_escalation,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _spec() -> SkillSpec:
    return SkillSpec(name="test_skill", description="d", brief="b")


def _ok_assembled() -> AssembledSkill:
    return AssembledSkill(
        spec=_spec(),
        ok=True,
        schema={"function": {"name": "test_skill"}},
        handler_code="def handle(*a, **kw): return ''",
        samples=[{"input": {}, "expect": ""}],
        raw_text="",
    )


async def test_ladder_returns_first_passing_tier(db, monkeypatch):
    seen: list[str] = []

    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        seen.append(tier)
        return _ok_assembled()

    async def fake_validate(assembled):
        # First tier fails, second tier passes.
        if seen.count(seen[-1]) and seen[-1] == "sonnet":
            return ValidationResult(
                ok=False, score=0.0, passed=0, total=3, failure_reason="all wrong"
            )
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier == "opus"
    assert seen == ["sonnet", "opus"]
    assert result.validation.ok is True
    assert [a.tier for a in result.attempts] == ["sonnet", "opus"]
    assert result.attempts[0].validation_ok is False
    assert result.attempts[1].validation_ok is True


async def test_ladder_returns_winning_tier_immediately(db, monkeypatch):
    seen: list[str] = []

    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        seen.append(tier)
        return _ok_assembled()

    async def fake_validate(assembled):
        return ValidationResult(ok=True, score=0.9, passed=3, total=3)

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier == "sonnet"
    assert seen == ["sonnet"]  # never escalated
    assert len(result.attempts) == 1


async def test_ladder_exhausted_all_tiers(db, monkeypatch):
    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        return _ok_assembled()

    async def fake_validate(assembled):
        return ValidationResult(
            ok=False, score=0.1, passed=0, total=3, failure_reason="bad bad"
        )

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier is None
    assert len(result.attempts) == 2
    assert all(not a.validation_ok for a in result.attempts)
    assert result.validation.failure_reason == "bad bad"


async def test_ladder_skips_validation_when_assembly_fails(db, monkeypatch):
    """If assembly itself fails on a tier, ladder records and moves on."""
    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        if tier == "sonnet":
            return AssembledSkill(spec=spec, ok=False, failure_reason="boom")
        return _ok_assembled()

    async def fake_validate(assembled):
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier == "opus"
    assert [a.assembled_ok for a in result.attempts] == [False, True]
    assert result.attempts[0].failure_reason == "boom"
