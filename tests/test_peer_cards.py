"""Tests for the Peer Cards module (ADR 0128)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from chimera.engines.peer_cards import (
    PeerCard,
    build_peer_card,
    build_self_card,
    consolidate_peer_cards,
    peers_dir,
    render_peer_card,
    write_peer_card,
)


# ── Stand-in record types (duck-typed; mirror real shape) ─────────


@dataclass
class _StubDecision:
    peer: str = "alpha"
    decision: str = "ALLOW"
    reason: str = ""
    drift_score: float | None = None
    recorded_at: str = "2026-05-24T10:00:00+00:00"


@dataclass
class _StubTrustEvent:
    timestamp: str = "2026-05-24T09:00:00+00:00"
    kind: str = "promote"
    from_tier: int = 1
    to_tier: int = 2
    reason: str = "autopromote"


@dataclass
class _StubTrustState:
    current_tier: int = 3
    tier_entered_at: str = "2026-05-24T08:00:00+00:00"
    last_readiness: float = 0.812
    history: list = field(default_factory=list)


# ── build_peer_card ───────────────────────────────────────────────


def test_build_peer_card_empty():
    card = build_peer_card("alpha")
    assert card.peer_name == "alpha"
    assert card.is_self is False
    assert card.trust_label is None
    assert card.recent_events == []
    assert card.cycles_since_last_contact is None


def test_build_peer_card_with_decisions_sorted_desc():
    decisions = [
        _StubDecision(decision="ALLOW", recorded_at="2026-05-24T09:00:00+00:00"),
        _StubDecision(decision="DEGRADE", reason="drift", drift_score=0.45,
                      recorded_at="2026-05-24T10:00:00+00:00"),
        _StubDecision(decision="ALLOW", recorded_at="2026-05-24T08:00:00+00:00"),
    ]
    card = build_peer_card("alpha", decisions=decisions)
    # Most-recent first.
    assert card.recent_events[0][1] == "DEGRADE"
    assert card.trust_label == "DEGRADE"
    assert card.composite_score == 0.45
    assert card.last_seen_at == "2026-05-24T10:00:00+00:00"


def test_build_peer_card_caps_recent_events_at_n():
    decisions = [
        _StubDecision(recorded_at=f"2026-05-24T{i:02d}:00:00+00:00")
        for i in range(12)
    ]
    card = build_peer_card("alpha", decisions=decisions, recent_n=3)
    assert len(card.recent_events) == 3


def test_build_peer_card_computes_cycles_since_contact():
    kfm = {"cycle": 100, "plan_kfm_state": "OK"}
    card = build_peer_card("alpha", kfm_snapshot=kfm, current_cycle=107)
    assert card.cycles_since_last_contact == 7
    assert card.kfm_snapshot == kfm


def test_build_peer_card_cycles_none_when_kfm_missing():
    card = build_peer_card("alpha", current_cycle=50)
    assert card.cycles_since_last_contact is None


def test_build_peer_card_cycles_clamped_at_zero():
    """If current_cycle < kfm cycle (clock skew), report 0 not negative."""
    kfm = {"cycle": 200}
    card = build_peer_card("alpha", kfm_snapshot=kfm, current_cycle=100)
    assert card.cycles_since_last_contact == 0


# ── build_self_card ──────────────────────────────────────────────


def test_build_self_card_minimal():
    state = _StubTrustState(current_tier=3, last_readiness=0.5)
    card = build_self_card(trust_state=state)
    assert card.peer_name == "self"
    assert card.is_self is True
    assert card.trust_label == "TRUSTED"
    assert card.composite_score == 0.5
    assert card.recent_events == []


def test_build_self_card_includes_history_desc():
    state = _StubTrustState(
        current_tier=5,
        history=[
            _StubTrustEvent(timestamp="2026-05-24T07:00:00+00:00", kind="promote"),
            _StubTrustEvent(timestamp="2026-05-24T09:00:00+00:00", kind="demote",
                            reason="drift"),
            _StubTrustEvent(timestamp="2026-05-24T08:00:00+00:00", kind="autopromote"),
        ],
    )
    card = build_self_card(trust_state=state)
    assert card.trust_label == "AUTONOMOUS"
    # Most-recent first.
    assert [e[1] for e in card.recent_events] == ["demote", "autopromote", "promote"]


def test_build_self_card_unknown_tier_labels_safely():
    state = _StubTrustState(current_tier=99)
    card = build_self_card(trust_state=state)
    # Falls back to stringified value rather than raising.
    assert card.trust_label == "99"


# ── Rendering ────────────────────────────────────────────────────


def test_render_peer_card_empty():
    out = render_peer_card(PeerCard(peer_name="alpha"))
    assert "# Peer card — alpha" in out
    assert "_(no state recorded)_" in out
    assert "_(none)_" in out


def test_render_peer_card_with_state_and_events():
    card = PeerCard(
        peer_name="alpha",
        trust_label="ALLOW",
        composite_score=0.812,
        recent_events=[("2026-05-24T10:00:00+00:00", "ALLOW", "handshake ok")],
        last_seen_at="2026-05-24T10:00:00+00:00",
        cycles_since_last_contact=3,
        kfm_snapshot={"cycle": 42, "plan_kfm_state": "OK"},
    )
    out = render_peer_card(card)
    assert "Trust label" in out
    assert "ALLOW" in out
    assert "0.812" in out
    assert "Cycles since contact" in out
    assert "## KFM snapshot" in out
    assert "plan_kfm_state" in out


def test_render_self_card_suppresses_kfm():
    card = PeerCard(
        peer_name="self",
        is_self=True,
        trust_label="TRUSTED",
        composite_score=0.5,
        kfm_snapshot={"cycle": 42},  # should NOT render for self
    )
    out = render_peer_card(card)
    assert "# Peer card — self" in out
    assert "## KFM snapshot" not in out


def test_render_includes_narrative_when_set():
    card = PeerCard(
        peer_name="alpha",
        narrative="Alpha tends to drift on long-running synthesis tasks.",
    )
    out = render_peer_card(card)
    assert "## Narrative" in out
    assert "long-running synthesis" in out


# ── write_peer_card sanitises path ────────────────────────────────


def test_write_peer_card_sanitises_unsafe_name(tmp_path: Path):
    card = PeerCard(peer_name="../etc/passwd")
    written = write_peer_card(tmp_path / "mind", card)
    # The slashes were sanitised — no escape from peers/.
    assert written.parent == peers_dir(tmp_path / "mind")
    assert "/" not in written.name
    assert ".." not in written.name


def test_write_peer_card_creates_dir(tmp_path: Path):
    card = PeerCard(peer_name="alpha")
    written = write_peer_card(tmp_path / "mind", card)
    assert written.exists()
    assert written.parent.name == "peers"


# ── consolidate_peer_cards ────────────────────────────────────────


def test_consolidate_writes_self_and_peers(tmp_path: Path):
    state = _StubTrustState(current_tier=3, last_readiness=0.5)
    paths = consolidate_peer_cards(
        mind_dir=tmp_path,
        trust_state=state,
        peer_names=["alpha", "beta"],
        decisions_by_peer={
            "alpha": [_StubDecision(decision="ALLOW")],
            "beta": [_StubDecision(decision="DEGRADE", reason="drift",
                                    recorded_at="2026-05-24T10:00:00+00:00")],
        },
        kfm_by_peer={"beta": {"cycle": 10, "plan_kfm_state": "OK"}},
        current_cycle=15,
    )
    assert len(paths) == 3
    names = sorted(p.name for p in paths)
    assert names == ["alpha.md", "beta.md", "self.md"]
    beta = (tmp_path / "peers" / "beta.md").read_text()
    assert "DEGRADE" in beta
    assert "Cycles since contact | 5" in beta


def test_consolidate_skips_self_when_no_trust_state(tmp_path: Path):
    paths = consolidate_peer_cards(mind_dir=tmp_path, peer_names=["alpha"])
    assert len(paths) == 1
    assert paths[0].name == "alpha.md"


def test_consolidate_empty_writes_nothing(tmp_path: Path):
    paths = consolidate_peer_cards(mind_dir=tmp_path)
    assert paths == []
    assert not peers_dir(tmp_path).exists()


# ── ADR 0128 doc presence ─────────────────────────────────────────


def test_adr_0128_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0128-peer-cards.md"
    )
    assert adr.exists()
    body = adr.read_text()
    # Locked design choices from the AskUserQuestion answers.
    assert "mind/peers" in body
    assert "ROTATE" in body
    assert "CHIMERA_PEER_CARD_LLM" in body
    assert "self.md" in body or "self-card" in body
