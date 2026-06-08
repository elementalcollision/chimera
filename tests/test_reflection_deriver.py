"""Tests for ReflectionEngine deriver wiring (ADR 0125)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.engines import ChronicleManager, ReflectionEngine
from chimera.engines.reflection import _deriver_enabled
from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Provider
from chimera.providers.tiers import Provider as ProviderKind


class _ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def stream(self, *a, **kw):  # pragma: no cover
        if False:
            yield ChatChunk(text="")

    async def complete_with_tools(self, *a, messages, **kw) -> ChatResponse:
        # Record which prompt this call corresponded to so tests can
        # assert call order (prose then deriver).
        text = messages[0].text() if messages else ""
        self.calls.append(text)
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
        text="Today I learned X. Tomorrow I'll Y.",
        tool_uses=[],
        stop_reason="stop",
        model_id="sonnet",
        provider="scripted",
    )


def _deriver_response(payload: dict) -> ChatResponse:
    return ChatResponse(
        text=json.dumps(payload),
        tool_uses=[],
        stop_reason="stop",
        model_id="sonnet",
        provider="scripted",
    )


# ── Default-off invariant guard (ADR 0125 amendment 2026-06-08) ───
#
# Decision: keep the deriver OPT-IN. It is fully wired and tested, but
# flipping the default to on would double per-cycle reflection spend and
# violate ADR 0125's own promotion gate (requires an enabled-flag soak
# that has not been run). These guards fail loudly if a future change
# silently flips the default.


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "nope"])
def test_deriver_default_off_unless_truthy_flag(value, monkeypatch):
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", value)
    assert _deriver_enabled() is False


def test_deriver_unset_is_off(monkeypatch):
    monkeypatch.delenv("CHIMERA_REFLECTION_DERIVER", raising=False)
    assert _deriver_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "On"])
def test_deriver_enabled_only_by_explicit_optin(value, monkeypatch):
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", value)
    assert _deriver_enabled() is True


# ── Flag off: no behavior change ──────────────────────────────────


@pytest.mark.asyncio
async def test_deriver_disabled_by_default(mind_dir, db, monkeypatch):
    """Without the env flag, ReflectionEngine makes exactly one call
    and writes no conclusions file."""
    monkeypatch.delenv("CHIMERA_REFLECTION_DERIVER", raising=False)
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    fake = _ScriptedProvider([_prose_response()])
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=5)
    assert result.skipped is False
    assert result.api_call_count == 1
    assert len(fake.calls) == 1
    assert not (mind_dir / "reflection_conclusions.jsonl").exists()


# ── Flag on: deriver runs and writes JSONL ────────────────────────


@pytest.mark.asyncio
async def test_deriver_enabled_writes_conclusions(mind_dir, db, monkeypatch):
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", "1")
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    chronicle.upsert_section(section_name="Morning Discovery", body="morning")
    payload = {
        "summary": "Shipped Phase 2.",
        "lessons_learned": ["small files ship faster"],
        "improvements_for_tomorrow": ["wire it sooner"],
        "themes": ["honcho", "deriver"],
    }
    fake = _ScriptedProvider([_prose_response(), _deriver_response(payload)])
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=7)
    assert result.skipped is False
    assert result.api_call_count == 2  # prose + deriver
    assert len(fake.calls) == 2
    # Second call uses the structured-output prompt.
    assert "STRICT JSON" in fake.calls[1]

    jsonl = mind_dir / "reflection_conclusions.jsonl"
    assert jsonl.exists()
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["cycle"] == 7
    assert row["summary"] == "Shipped Phase 2."
    assert row["lessons_learned"] == ["small files ship faster"]
    assert row["themes"] == ["honcho", "deriver"]
    assert "at" in row


# ── Deriver failure does not fail reflection ──────────────────────


@pytest.mark.asyncio
async def test_deriver_failure_does_not_fail_reflection(mind_dir, db, monkeypatch):
    """If the deriver call raises, the reflection still succeeds and
    the JSONL file is not created. The prose chronicle is preserved."""
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", "1")
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")

    class _FailingDeriver(_ScriptedProvider):
        async def complete_with_tools(self, *a, messages, **kw):
            self.calls.append(messages[0].text() if messages else "")
            if len(self.calls) == 1:
                # First (prose) call succeeds.
                return _prose_response()
            raise RuntimeError("deriver provider down")

    fake = _FailingDeriver([])
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=9)
    assert result.skipped is False
    assert result.failure_reason is None
    text = (mind_dir / "CHRONICLE.md").read_text()
    assert "Today I learned X" in text
    assert not (mind_dir / "reflection_conclusions.jsonl").exists()


# ── Unparseable deriver output yields no JSONL row ────────────────


@pytest.mark.asyncio
async def test_deriver_empty_conclusions_skips_jsonl(mind_dir, db, monkeypatch):
    """When the model returns prose instead of JSON, we still bill the
    API call but write no row (empty conclusions filtered)."""
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", "1")
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    garbage = ChatResponse(
        text="I cannot comply with that request.",
        tool_uses=[],
        stop_reason="stop",
        model_id="sonnet",
        provider="scripted",
    )
    fake = _ScriptedProvider([_prose_response(), garbage])
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    result = await eng.run(cycle=11)
    assert result.api_call_count == 2  # both calls billed
    assert not (mind_dir / "reflection_conclusions.jsonl").exists()


# ── JSONL accumulates across cycles ───────────────────────────────


@pytest.mark.asyncio
async def test_deriver_jsonl_appends_across_cycles(mind_dir, db, monkeypatch):
    monkeypatch.setenv("CHIMERA_REFLECTION_DERIVER", "1")
    chronicle = ChronicleManager(mind_dir / "CHRONICLE.md")
    payload_a = {"summary": "day A", "lessons_learned": [],
                 "improvements_for_tomorrow": [], "themes": ["a"]}
    payload_b = {"summary": "day B", "lessons_learned": [],
                 "improvements_for_tomorrow": [], "themes": ["b"]}
    fake = _ScriptedProvider([
        _prose_response(), _deriver_response(payload_a),
        _prose_response(), _deriver_response(payload_b),
    ])
    eng = ReflectionEngine(
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        mind_dir=mind_dir,
        chronicle=chronicle,
    )
    await eng.run(cycle=20)
    await eng.run(cycle=21)
    rows = [
        json.loads(line)
        for line in (mind_dir / "reflection_conclusions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [r["cycle"] for r in rows] == [20, 21]
    assert [r["summary"] for r in rows] == ["day A", "day B"]


# ── ADR 0125 doc presence ─────────────────────────────────────────


def test_adr_0125_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0125-wire-deriver-to-reflection.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "CHIMERA_REFLECTION_DERIVER" in body
    assert "0124" in body
    # Amendment 2026-06-08: the keep-opt-in decision must be recorded.
    assert "Amendment" in body
    assert "opt-in" in body.lower()
