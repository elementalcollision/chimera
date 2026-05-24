"""Tests for ReasoningTier wiring (ADR 0127)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.budget import ReasoningTier, tier_for_reasoning
from chimera.engines import ChronicleManager, ReflectionEngine
from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Provider
from chimera.providers.tiers import Provider as ProviderKind


# ── tier_for_reasoning() mapping ───────────────────────────────────


def test_tier_for_reasoning_none_returns_default():
    assert tier_for_reasoning(None) == "sonnet"
    assert tier_for_reasoning(None, default="haiku") == "haiku"


def test_tier_for_reasoning_minimal_maps_to_haiku():
    assert tier_for_reasoning(ReasoningTier.MINIMAL) == "haiku"


def test_tier_for_reasoning_normal_maps_to_sonnet():
    assert tier_for_reasoning(ReasoningTier.NORMAL) == "sonnet"


def test_tier_for_reasoning_deep_maps_to_opus():
    assert tier_for_reasoning(ReasoningTier.DEEP) == "opus"


def test_tier_for_reasoning_max_maps_to_opus():
    """MAX intentionally falls back to opus at single-call routing;
    panel behavior lives at a different layer (ADR 0107)."""
    assert tier_for_reasoning(ReasoningTier.MAX) == "opus"


def test_tier_for_reasoning_ignores_default_when_tier_given():
    """A real ReasoningTier overrides ``default`` entirely."""
    assert tier_for_reasoning(ReasoningTier.MINIMAL, default="opus") == "haiku"


# ── ReflectionEngine accepts ReasoningTier ─────────────────────────


class _ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    async def stream(self, *a, **kw):  # pragma: no cover
        if False:
            yield ChatChunk(text="")

    async def complete_with_tools(self, *a, **kw) -> ChatResponse:
        if not self._responses:
            raise AssertionError("FakeProvider out of responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _disable_v470_gates(monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINE_GATES_ENABLED", "0")


@pytest.fixture
def mind_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mind"
    d.mkdir()
    return d


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _prose_response() -> ChatResponse:
    return ChatResponse(
        text="ok", tool_uses=[], stop_reason="stop",
        model_id="m", provider="scripted",
    )


def test_reflection_engine_default_tier_unchanged(mind_dir, db):
    """Without reasoning_tier, the engine keeps its legacy sonnet default."""
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: _ScriptedProvider([])},
        db=db,
        mind_dir=mind_dir,
        chronicle=ChronicleManager(mind_dir / "CHRONICLE.md"),
    )
    assert eng._tier == "sonnet"
    assert eng._reasoning_tier is None


def test_reflection_engine_minimal_tier_resolves_to_haiku(mind_dir, db):
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: _ScriptedProvider([])},
        db=db,
        mind_dir=mind_dir,
        chronicle=ChronicleManager(mind_dir / "CHRONICLE.md"),
        reasoning_tier=ReasoningTier.MINIMAL,
    )
    assert eng._tier == "haiku"
    assert eng._reasoning_tier is ReasoningTier.MINIMAL


def test_reflection_engine_deep_tier_resolves_to_opus(mind_dir, db):
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: _ScriptedProvider([])},
        db=db,
        mind_dir=mind_dir,
        chronicle=ChronicleManager(mind_dir / "CHRONICLE.md"),
        reasoning_tier=ReasoningTier.DEEP,
    )
    assert eng._tier == "opus"


def test_reflection_engine_reasoning_tier_overrides_literal_tier(mind_dir, db):
    """If both are given, ReasoningTier wins — caller opted in."""
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: _ScriptedProvider([])},
        db=db,
        mind_dir=mind_dir,
        chronicle=ChronicleManager(mind_dir / "CHRONICLE.md"),
        tier="haiku",
        reasoning_tier=ReasoningTier.DEEP,
    )
    assert eng._tier == "opus"


# ── ADR 0127 doc presence ─────────────────────────────────────────


def test_adr_0127_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0127-reasoning-tier-wiring.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "tier_for_reasoning" in body
    assert "0123" in body
