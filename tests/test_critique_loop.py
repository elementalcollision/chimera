"""Tests for v4.7 critique-and-revise feedback loop (ADR 0030)."""

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
from chimera.skills.critique import build_critique_prompt


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _spec() -> SkillSpec:
    return SkillSpec(name="rev_demo", description="d", brief="b")


def _ok_assembled(text: str = "def handle(): pass") -> AssembledSkill:
    return AssembledSkill(
        spec=_spec(),
        ok=True,
        schema={"function": {"name": "rev_demo"}},
        handler_code=text,
        samples=[{"input": {}, "expect": ""}],
        raw_text="",
    )


def test_build_critique_prompt_includes_handler_and_outcomes():
    spec = _spec()
    assembled = _ok_assembled("async def handle(args, ctx): return ''")
    validation = ValidationResult(
        ok=False, score=0.0, passed=0, total=2,
        sample_outcomes=[
            {"index": 0, "ok": False, "reason": "missing arg"},
            {"index": 1, "ok": False, "reason": "TypeError"},
        ],
        failure_reason="0/2 passed",
    )
    prompt = build_critique_prompt(spec, assembled, validation)
    assert "rev_demo" in prompt
    assert "async def handle" in prompt
    assert "missing arg" in prompt
    assert "0/2 passed" in prompt
    # Same three-fence contract as the assembler.
    assert "schema" in prompt and "python" in prompt and "samples" in prompt


async def test_ladder_revises_when_first_validation_fails(db, monkeypatch):
    """v4.7: a failed validation triggers one critique pass on the same tier
    before escalating. If the revision passes, return early."""
    seen_tiers: list[str] = []
    revisions: list[str] = []

    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        seen_tiers.append(tier)
        return _ok_assembled("first")

    async def fake_validate(assembled):
        if assembled.handler_code == "first":
            return ValidationResult(
                ok=False, score=0.0, passed=0, total=3,
                failure_reason="all wrong",
                sample_outcomes=[{"index": 0, "ok": False, "reason": "x"}],
            )
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    async def fake_critique(spec, assembled, validation, *, providers, db, cycle, tier, max_tokens=2048):
        revisions.append(tier)
        return _ok_assembled("revised")

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)
    monkeypatch.setattr("chimera.skills.ladder.critique_and_revise", fake_critique)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier == "sonnet"  # revision succeeded on sonnet, no escalation
    assert seen_tiers == ["sonnet"]
    assert revisions == ["sonnet"]
    assert len(result.attempts) == 1
    assert result.attempts[0].revised is True
    assert result.attempts[0].revised_score == 1.0


async def test_ladder_escalates_when_revision_still_fails(db, monkeypatch):
    """If revision also fails, ladder escalates to the next tier."""
    seen_tiers: list[str] = []

    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        seen_tiers.append(tier)
        return _ok_assembled("v_" + tier)

    async def fake_validate(assembled):
        # sonnet original AND sonnet revised both fail; opus original passes.
        if assembled.handler_code in ("v_sonnet", "revised_sonnet"):
            return ValidationResult(
                ok=False, score=0.2, passed=0, total=3,
                failure_reason="still wrong",
                sample_outcomes=[],
            )
        return ValidationResult(ok=True, score=1.0, passed=3, total=3)

    async def fake_critique(spec, assembled, validation, *, providers, db, cycle, tier, max_tokens=2048):
        return _ok_assembled("revised_" + tier)

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)
    monkeypatch.setattr("chimera.skills.ladder.critique_and_revise", fake_critique)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1,
        tiers=("sonnet", "opus"), witnesses=None,
    )
    assert result.winning_tier == "opus"
    assert seen_tiers == ["sonnet", "opus"]
    assert result.attempts[0].revised is True
    assert result.attempts[0].validation_ok is False
    assert result.attempts[0].revised_score == 0.2


async def test_ladder_skips_revision_when_critic_fails(db, monkeypatch):
    """If the critic returns None, ladder records `revised=False` and moves on."""
    async def fake_assemble(spec, *, providers, db, cycle, tier, max_tokens=2048):
        return _ok_assembled("first")

    async def fake_validate(assembled):
        return ValidationResult(
            ok=False, score=0.0, passed=0, total=3,
            failure_reason="all wrong", sample_outcomes=[],
        )

    async def fake_critique(*a, **kw):
        return None

    monkeypatch.setattr("chimera.skills.ladder.assemble_skill", fake_assemble)
    monkeypatch.setattr("chimera.skills.ladder.validate_skill", fake_validate)
    monkeypatch.setattr("chimera.skills.ladder.critique_and_revise", fake_critique)

    result = await assemble_with_escalation(
        _spec(), providers={}, db=db, cycle=1, tiers=("sonnet",), witnesses=None,
    )
    assert result.winning_tier is None
    assert result.attempts[0].revised is False
