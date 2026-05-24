"""Tests for the ROTATE-phase peer-cards wiring (ADR 0129).

The loop-level integration is what the deterministic peer-cards
module (ADR 0128) plugs into. These tests instantiate a ChimeraLoop
and exercise the rotation path directly, checking that:

  * Rotation fires `_consolidate_peer_cards_safe` (default-on).
  * The self-card is written to `mind/peers/self.md`.
  * `CHIMERA_PEER_CARDS_ON_ROTATE=0` opts out cleanly.
  * Peer-cards failures do NOT break rotation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import ChimeraLoop, LoopConfig


@pytest.fixture
def mind_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mind"
    d.mkdir()
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def loop(mind_dir: Path, state_dir: Path) -> ChimeraLoop:
    return ChimeraLoop(LoopConfig(mind_dir=mind_dir, state_dir=state_dir))


# ── default-on consolidation ──────────────────────────────────────


def test_rotate_consolidates_self_card_by_default(loop, mind_dir, monkeypatch):
    monkeypatch.delenv("CHIMERA_PEER_CARDS_ON_ROTATE", raising=False)
    loop._consolidate_peer_cards_safe()
    self_card = mind_dir / "peers" / "self.md"
    assert self_card.exists()
    body = self_card.read_text()
    assert "# Peer card — self" in body


def test_rotate_skips_when_env_flag_off(loop, mind_dir, monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_CARDS_ON_ROTATE", "0")
    loop._consolidate_peer_cards_safe()
    assert not (mind_dir / "peers").exists()


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
def test_rotate_env_flag_accepts_common_off_strings(
    loop, mind_dir, monkeypatch, value,
):
    monkeypatch.setenv("CHIMERA_PEER_CARDS_ON_ROTATE", value)
    loop._consolidate_peer_cards_safe()
    assert not (mind_dir / "peers").exists()


# ── failure isolation ────────────────────────────────────────────


def test_peer_cards_failure_does_not_raise(loop, mind_dir, monkeypatch):
    """A blown-up consolidate_peer_cards call must not propagate —
    rotation is load-bearing and peer cards are a bonus signal."""
    monkeypatch.delenv("CHIMERA_PEER_CARDS_ON_ROTATE", raising=False)

    def boom(**kwargs):
        raise RuntimeError("intentional test failure")

    monkeypatch.setattr(
        "chimera.engines.peer_cards.consolidate_peer_cards", boom,
    )
    # Should NOT raise.
    loop._consolidate_peer_cards_safe()
    assert not (mind_dir / "peers" / "self.md").exists()


# ── integration via the actual _phase_rotate path ─────────────────


@pytest.mark.asyncio
async def test_phase_rotate_writes_peer_cards_when_forced(loop, mind_dir, monkeypatch):
    """Forcing rotation through the real _phase_rotate path triggers
    peer-cards consolidation. We exercise the path end-to-end rather
    than relying on the helper being called directly."""
    monkeypatch.delenv("CHIMERA_PEER_CARDS_ON_ROTATE", raising=False)
    # Run one cycle to initialise session state.
    await loop.run_one_cycle()
    # Force the next rotate call to actually rotate.
    loop._force_rotation_reason = "test-forced"
    rotated = await loop._phase_rotate()
    assert rotated is True
    assert (mind_dir / "peers" / "self.md").exists()


# ── ADR 0129 doc presence ─────────────────────────────────────────


def test_adr_0129_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0129-peer-cards-rotate-wiring.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "CHIMERA_PEER_CARDS_ON_ROTATE" in body
    assert "_phase_rotate" in body
    assert "0128" in body
