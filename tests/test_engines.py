"""Tests for DiscoveryEngine + CuriosityEngine + ReflectionEngine.

Uses scripted FakeProviders to avoid live calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.engines import (
    ChronicleManager,
    CuriosityEngine,
    DiscoveryEngine,
    ReflectionEngine,
)
from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Provider
from chimera.providers.tiers import Provider as ProviderKind
from chimera.tools import ToolRegistry, register_core_tools


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
    """These legacy engine tests pre-date the v4.70 signal-density gates
    and don't seed enough api_calls or chronicle to pass them. Disable
    the master switch for this module so they test engine mechanics."""
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


# ── Discovery ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discovery_engine_writes_morning_section(mind_dir, db):
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    fake = _ScriptedProvider(
        [
            ChatResponse(
                text="- Theme A surfaced repeatedly\n- One stuck retry on Y\n- Surprise: Z worked first try",
                tool_uses=[],
                stop_reason="stop",
                input_tokens=120,
                output_tokens=40,
                model_id="haiku",
                provider="scripted",
            )
        ]
    )
    eng = DiscoveryEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=2)
    assert result.skipped is False
    assert result.api_call_count == 1
    text = (mind_dir / "CHRONICLE.md").read_text()
    assert "### Morning Discovery" in text
    assert "Theme A surfaced repeatedly" in text


@pytest.mark.asyncio
async def test_discovery_records_failure_outcome(mind_dir, db):
    class _Bad(_ScriptedProvider):
        async def complete_with_tools(self, *a, **kw):
            raise RuntimeError("provider down")

    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    bad = _Bad([])
    eng = DiscoveryEngine(
        providers={ProviderKind.ANTHROPIC: bad, ProviderKind.OPENROUTER: bad},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=2)
    assert result.skipped is False
    assert result.failure_reason == "provider down"
    rows = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    assert rows[0]["outcome"] == "non_retriable"


# ── Reflection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflection_engine_replaces_evening_section(mind_dir, db):
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    chronicle.upsert_section(section_name="Morning Discovery", body="morning content")
    fake = _ScriptedProvider(
        [
            ChatResponse(
                text="Today I learned X. Tomorrow I'll Y.",
                tool_uses=[],
                stop_reason="stop",
                model_id="sonnet",
                provider="scripted",
            )
        ]
    )
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=10)
    assert result.skipped is False
    text = (mind_dir / "CHRONICLE.md").read_text()
    assert "### Evening Reflection" in text
    assert "Today I learned X" in text
    # Morning section is preserved.
    assert "morning content" in text


# ── Curiosity ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_curiosity_engine_writes_project_dir_and_chronicle(mind_dir, db):
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    reg = ToolRegistry()
    register_core_tools(reg)
    # Single-turn provider response (no tool use) so ActExecutor exits cleanly.
    fake = _ScriptedProvider(
        [
            ChatResponse(
                text=(
                    "Multi-LLM frameworks are converging on policy-pipeline tool gating. "
                    "Source: https://example.com/article."
                ),
                tool_uses=[],
                stop_reason="stop",
                model_id="sonnet",
                provider="scripted",
            )
        ]
    )
    eng = CuriosityEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        registry=reg,
        mind_dir=mind_dir,
        chronicle=chronicle,
        seed_topic="What is a tool-policy pipeline?",
    )
    result = await eng.run(cycle=8)
    assert result.skipped is False
    assert result.api_call_count == 1
    # Project dir created.
    projects = list((mind_dir / "wiki" / "projects").iterdir())
    assert len(projects) == 1
    q_dir = projects[0]
    assert q_dir.name.startswith("q001-")
    assert (q_dir / "question.md").exists()
    assert (q_dir / "notes.md").exists()
    notes = (q_dir / "notes.md").read_text()
    assert "policy-pipeline" in notes
    # Chronicle has a Midday Curiosity section pointing at it.
    chron = (mind_dir / "CHRONICLE.md").read_text()
    assert "### Midday Curiosity" in chron
    assert "tool-policy pipeline" in chron.lower()


@pytest.mark.asyncio
async def test_curiosity_engine_increments_question_number(mind_dir, db):
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    reg = ToolRegistry()
    register_core_tools(reg)
    fake = _ScriptedProvider(
        [
            ChatResponse(text="first result", tool_uses=[], stop_reason="stop", model_id="x", provider="s"),
            ChatResponse(text="second result", tool_uses=[], stop_reason="stop", model_id="x", provider="s"),
        ]
    )
    eng = CuriosityEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        registry=reg,
        mind_dir=mind_dir,
        chronicle=chronicle,
        seed_topic="topic one",
    )
    await eng.run(cycle=8)
    eng._seed_topic = "topic two"
    await eng.run(cycle=9)
    projects = sorted(p.name for p in (mind_dir / "wiki" / "projects").iterdir())
    assert projects[0].startswith("q001-")
    assert projects[1].startswith("q002-")
