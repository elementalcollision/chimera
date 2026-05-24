"""Tests for the `chimera peers cards` CLI verb (ADR 0131)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.cli import main


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    monkeypatch.delenv("CHIMERA_PEER_CARD_LLM", raising=False)
    return mind, state


# ── happy path ────────────────────────────────────────────────────


def test_peers_cards_writes_self_card(env, capsys):
    mind, _ = env
    rc = main(["peers", "cards"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote 1 card" in out  # only self, no registered peers in test env
    assert (mind / "peers" / "self.md").exists()


def test_peers_cards_json_output(env, capsys):
    mind, _ = env
    rc = main(["peers", "cards", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["narrative"] is False
    assert payload["peers"] == []
    assert any("self.md" in p for p in payload["written"])


def test_peers_cards_narrative_flag_sets_env(env, monkeypatch, capsys):
    """--narrative sets CHIMERA_PEER_CARD_LLM=1 for the call.

    Without providers it skips silently, leaving no narrative section
    in the rendered card — but the env should be set during the call.
    """
    mind, _ = env
    # Capture env state during the call.
    seen: dict[str, str | None] = {}

    real_enrich = None
    from chimera.core import loop as _loop_mod

    def spy_enrich(self, cards):
        import os
        seen["flag"] = os.environ.get("CHIMERA_PEER_CARD_LLM")
        # Don't actually call providers in the test.
        return real_enrich  # no-op

    monkeypatch.setattr(
        _loop_mod.ChimeraLoop, "_enrich_cards_with_narratives", spy_enrich,
    )
    rc = main(["peers", "cards", "--narrative"])
    assert rc == 0
    assert seen["flag"] == "1"
    body = (mind / "peers" / "self.md").read_text()
    # Spy bypassed the actual call → no narrative produced.
    assert "## Narrative" not in body


def test_peers_cards_default_is_deterministic_only(env, monkeypatch, capsys):
    """Without --narrative the enrichment helper is never called."""
    called = {"n": 0}
    from chimera.core import loop as _loop_mod

    def spy_enrich(self, cards):
        called["n"] += 1

    monkeypatch.setattr(
        _loop_mod.ChimeraLoop, "_enrich_cards_with_narratives", spy_enrich,
    )
    rc = main(["peers", "cards"])
    assert rc == 0
    assert called["n"] == 0


def test_peers_cards_mind_dir_override(tmp_path: Path, monkeypatch, capsys):
    """--mind-dir overrides the env-derived location for this call."""
    alt_mind = tmp_path / "alt-mind"
    state = tmp_path / "state"
    alt_mind.mkdir()
    state.mkdir()
    monkeypatch.delenv("CHIMERA_MIND_DIR", raising=False)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    rc = main([
        "peers", "cards",
        "--mind-dir", str(alt_mind),
        "--state-dir", str(state),
    ])
    assert rc == 0
    assert (alt_mind / "peers" / "self.md").exists()


# ── parser registration ──────────────────────────────────────────


def test_peers_help_lists_cards_subcommand(capsys):
    """`chimera peers --help` should mention the cards subcommand."""
    with pytest.raises(SystemExit):
        main(["peers", "--help"])
    out = capsys.readouterr().out
    assert "cards" in out


def test_peers_cards_help_lists_narrative_flag(capsys):
    with pytest.raises(SystemExit):
        main(["peers", "cards", "--help"])
    out = capsys.readouterr().out
    assert "--narrative" in out
    assert "CHIMERA_PEER_CARD_LLM" in out


# ── ADR 0131 doc presence ─────────────────────────────────────────


def test_adr_0131_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0131-peers-cli-verb.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "peers cards" in body
    assert "--narrative" in body
    assert "0128" in body
