"""Tests for the dialectic API (ADR 0133)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.a2a.dialectic import (
    DialecticContext,
    build_dialectic_prompt,
    gather_dialectic_context,
    trim_answer,
)


# ── gather_dialectic_context ──────────────────────────────────────


def test_gather_unknown_peer_empty(tmp_path: Path):
    mind = tmp_path / "mind"
    mind.mkdir()
    ctx = gather_dialectic_context("ghost", mind_dir=mind)
    assert ctx.peer_name == "ghost"
    assert ctx.peer_card_markdown is None
    assert ctx.recent_decisions == []
    assert ctx.beliefs == []
    assert ctx.kfm_snapshot is None
    assert ctx.sources_used == []
    assert ctx.is_empty()


def test_gather_reads_peer_card(tmp_path: Path):
    mind = tmp_path / "mind"
    (mind / "peers").mkdir(parents=True)
    (mind / "peers" / "alpha.md").write_text("# Peer card — alpha\n\nstate.")
    ctx = gather_dialectic_context("alpha", mind_dir=mind)
    assert ctx.peer_card_markdown is not None
    assert "Peer card — alpha" in ctx.peer_card_markdown
    assert any(s.startswith("peer_card:") for s in ctx.sources_used)


def test_gather_sanitises_path(tmp_path: Path):
    """A nasty peer name shouldn't escape mind/peers/."""
    mind = tmp_path / "mind"
    mind.mkdir()
    ctx = gather_dialectic_context("../etc/passwd", mind_dir=mind)
    # No card found (sanitised filename doesn't exist) — empty context.
    assert ctx.is_empty()


def test_gather_reads_trust_journal_decisions(tmp_path: Path, monkeypatch):
    """Trust-journal decisions land in ``ctx.recent_decisions``, newest first."""
    from dataclasses import dataclass

    @dataclass
    class _Dec:
        decision: str
        reason: str
        drift_score: float | None
        recorded_at: str

    def fake_list(peer):
        assert peer == "alpha"
        return [
            _Dec("ALLOW", "ok", 0.1, "2026-05-24T09:00:00+00:00"),
            _Dec("DEGRADE", "drift", 0.5, "2026-05-24T10:00:00+00:00"),
        ]

    monkeypatch.setattr(
        "chimera.a2a.peer_trust_journal.list_decisions", fake_list,
    )
    mind = tmp_path / "mind"
    mind.mkdir()
    ctx = gather_dialectic_context("alpha", mind_dir=mind)
    assert len(ctx.recent_decisions) == 2
    assert ctx.recent_decisions[0]["decision"] == "DEGRADE"  # newest first
    assert any(s.startswith("trust_journal:") for s in ctx.sources_used)


def test_gather_caps_decisions_at_recent_n(tmp_path: Path, monkeypatch):
    from dataclasses import dataclass

    @dataclass
    class _Dec:
        decision: str
        reason: str
        drift_score: float | None
        recorded_at: str

    decisions = [
        _Dec("ALLOW", "", 0.1, f"2026-05-24T{i:02d}:00:00+00:00")
        for i in range(12)
    ]
    monkeypatch.setattr(
        "chimera.a2a.peer_trust_journal.list_decisions", lambda peer: decisions,
    )
    mind = tmp_path / "mind"
    mind.mkdir()
    ctx = gather_dialectic_context("alpha", mind_dir=mind, recent_decisions_n=3)
    assert len(ctx.recent_decisions) == 3


# ── build_dialectic_prompt ────────────────────────────────────────


def test_build_prompt_unknown_uses_no_data_template():
    ctx = DialecticContext(peer_name="ghost")
    prompt = build_dialectic_prompt(ctx, "what do we know?")
    assert "no recorded information" in prompt
    assert "ghost" in prompt
    assert "what do we know?" in prompt


def test_build_prompt_with_card_includes_grounding():
    ctx = DialecticContext(
        peer_name="alpha",
        peer_card_markdown="# Peer card — alpha\nTrust label: ALLOW",
        recent_decisions=[{
            "decision": "ALLOW", "reason": "handshake ok",
            "drift_score": 0.1,
            "recorded_at": "2026-05-24T10:00:00+00:00",
        }],
        sources_used=["peer_card:alpha.md", "trust_journal:1"],
    )
    prompt = build_dialectic_prompt(ctx, "is alpha trustworthy?")
    assert "alpha" in prompt
    assert "Peer card" in prompt
    assert "ALLOW" in prompt
    assert "handshake ok" in prompt
    assert "is alpha trustworthy?" in prompt
    assert "UNDER 120 words" in prompt


def test_build_prompt_kfm_block_when_absent():
    ctx = DialecticContext(
        peer_name="alpha",
        peer_card_markdown="x",
    )
    prompt = build_dialectic_prompt(ctx, "?")
    assert "(not fetched)" in prompt


def test_build_prompt_renders_beliefs_when_present():
    ctx = DialecticContext(
        peer_name="alpha",
        peer_card_markdown="x",
        beliefs=[{
            "observer": "alpha", "observed": "alpha",
            "label": "DISTRUSTS", "drift_score": 0.7,
            "recorded_at": "2026-05-24T10:00:00+00:00",
        }],
    )
    prompt = build_dialectic_prompt(ctx, "?")
    assert "DISTRUSTS" in prompt
    assert "alpha→alpha" in prompt


# ── trim_answer ──────────────────────────────────────────────────


def test_trim_answer_strips_fence():
    out = trim_answer("```\nAlpha is trusted.\n```")
    assert out == "Alpha is trusted."


def test_trim_answer_caps_words():
    long = " ".join(["w"] * 300)
    out = trim_answer(long, word_cap=10)
    assert out.endswith("…")
    assert len(out.split()) <= 11


def test_trim_answer_empty():
    assert trim_answer("") == ""
    assert trim_answer("   \n  ") == ""


# ── MCP tool ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_tool_returns_grounded_prompt(tmp_path: Path, monkeypatch):
    """The MCP `chimera-ask` handler returns JSON with the assembled prompt."""
    from chimera.server.dialectic_tool import _handler
    from chimera.tools import DispatchContext

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    (mind / "peers").mkdir(parents=True)
    state.mkdir()
    (mind / "peers" / "alpha.md").write_text("# Peer card — alpha\nstate.")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))

    out = await _handler(
        {"peer_name": "alpha", "question": "is alpha ok?"},
        DispatchContext(),
    )
    payload = json.loads(out)
    assert payload["peer_name"] == "alpha"
    assert payload["question"] == "is alpha ok?"
    assert "alpha" in payload["prompt"]
    assert "Peer card — alpha" in payload["prompt"]
    assert payload["is_empty_context"] is False
    assert any(s.startswith("peer_card:") for s in payload["sources_used"])


@pytest.mark.asyncio
async def test_ask_tool_missing_args_returns_error():
    from chimera.server.dialectic_tool import _handler
    from chimera.tools import DispatchContext

    out = await _handler({"peer_name": "alpha"}, DispatchContext())
    payload = json.loads(out)
    assert "error" in payload


@pytest.mark.asyncio
async def test_ask_tool_unknown_peer_returns_empty_context(
    tmp_path: Path, monkeypatch,
):
    from chimera.server.dialectic_tool import _handler
    from chimera.tools import DispatchContext

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    out = await _handler(
        {"peer_name": "ghost", "question": "?"}, DispatchContext(),
    )
    payload = json.loads(out)
    assert payload["is_empty_context"] is True
    assert "no recorded information" in payload["prompt"]


# ── CLI verb ──────────────────────────────────────────────────────


def test_cli_peers_ask_prompt_only(tmp_path: Path, monkeypatch, capsys):
    from chimera.cli import main

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    (mind / "peers").mkdir(parents=True)
    state.mkdir()
    (mind / "peers" / "alpha.md").write_text("# Peer card — alpha\nstate.")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    rc = main([
        "peers", "ask", "alpha", "is alpha trustworthy?",
        "--prompt-only",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "Peer card — alpha" in out
    assert "is alpha trustworthy?" in out


def test_cli_peers_ask_prompt_only_json(tmp_path: Path, monkeypatch, capsys):
    from chimera.cli import main

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    rc = main([
        "peers", "ask", "ghost", "who?", "--prompt-only", "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["peer_name"] == "ghost"
    assert payload["is_empty_context"] is True


def test_cli_peers_ask_help_lists_args(capsys):
    from chimera.cli import main

    with pytest.raises(SystemExit):
        main(["peers", "ask", "--help"])
    out = capsys.readouterr().out
    assert "peer_name" in out
    assert "question" in out
    assert "--prompt-only" in out


# ── ADR 0133 doc presence ─────────────────────────────────────────


def test_adr_0133_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0133-dialectic-api.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "peers ask" in body
    assert "chimera-ask" in body
    assert "0128" in body


def test_build_prompt_includes_cross_session_sentences():
    """Both cross-session guidance sentences appear in build_dialectic_prompt output."""
    from chimera.a2a.dialectic import DialecticContext, build_dialectic_prompt

    ctx = DialecticContext(
        peer_name="alpha",
        peer_card_markdown="# Peer card — alpha",
        recent_decisions=[
            {
                "decision": "ALLOW",
                "reason": "handshake ok",
                "drift_score": 0.1,
                "recorded_at": "2026-05-24T10:00:00+00:00",
            }
        ],
    )
    prompt = build_dialectic_prompt(ctx, "did alpha change?")
    assert "When the question requires information from multiple sessions, integrate facts across the entire history." in prompt
    assert "When a fact stated in an earlier session is contradicted by a later session, prefer the later session." in prompt
