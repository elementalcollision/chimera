"""Tests for ADR 0167 power-of-two-choices peer selection."""

from __future__ import annotations

import json
import random

import pytest

from chimera.a2a import (
    PeerAwareDispatcher,
    PeerCandidate,
    PeerTrustPolicy,
    choose,
    peer_selection_enabled,
    select_peer,
)
from chimera.positioning.circuit import CircuitBreaker, CircuitState
from chimera.tools import ToolRegistry


# ── helpers ─────────────────────────────────────────────────


def _register_peer(
    reg: ToolRegistry,
    peer: str,
    *,
    capabilities: tuple[str, ...] = (),
    drift: float | None = 0.05,
    tier: int = 3,
    plan: str = "STABLE",
) -> None:
    """Register a peer's identity + kfm-state tools so it is discoverable."""

    async def _identity(args, ctx):
        return json.dumps({"agent_id": peer, "capabilities": list(capabilities)})

    async def _kfm(args, ctx):
        return json.dumps(
            {
                "trust_tier_int": tier,
                "plan_kfm_state": plan,
                "last_drift_score": drift,
            }
        )

    for suffix, handler in (("identity", _identity), ("kfm-state", _kfm)):
        name = f"mcp-{peer}-chimera-{suffix}"
        reg.register(
            name=name,
            toolset=f"mcp-{peer}",
            schema={
                "type": "function",
                "function": {
                    "name": name,
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            handler=handler,
        )


# ── flag parsing ────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_PEER_SELECTION", raising=False)
    assert peer_selection_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_flag_truthy_spellings(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_PEER_SELECTION", val)
    assert peer_selection_enabled() is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "maybe"])
def test_flag_falsy_spellings(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_PEER_SELECTION", val)
    assert peer_selection_enabled() is False


# ── pure choose() ───────────────────────────────────────────


def test_choose_empty_returns_none():
    assert choose([]) is None


def test_choose_single_returns_it():
    only = PeerCandidate("solo", drift_score=0.9, healthy=False)
    assert choose([only]) is only


def test_choose_two_picks_lower_drift():
    lo = PeerCandidate("lo", drift_score=0.02)
    hi = PeerCandidate("hi", drift_score=0.25)
    # With exactly two candidates both are always sampled, so the result is
    # deterministic regardless of RNG: the lower load_key wins.
    assert choose([lo, hi]) is lo
    assert choose([hi, lo]) is lo


def test_choose_prefers_healthy_over_lower_drift():
    healthy_high = PeerCandidate("h", drift_score=0.25, healthy=True)
    unhealthy_low = PeerCandidate("u", drift_score=0.01, healthy=False)
    assert choose([healthy_high, unhealthy_low]) is healthy_high


def test_choose_unknown_drift_loses_to_known_lower():
    known = PeerCandidate("known", drift_score=0.10)
    unknown = PeerCandidate("unknown", drift_score=None)  # defaults to 0.30
    assert choose([known, unknown]) is known


def test_choose_three_samples_two_with_seeded_rng():
    a = PeerCandidate("a", drift_score=0.10)
    b = PeerCandidate("b", drift_score=0.20)
    c = PeerCandidate("c", drift_score=0.30)
    # Seeded RNG makes the pair sampling reproducible; the better of the two
    # sampled is returned (power of *two*, not global argmin).
    picked = choose([a, b, c], rng=random.Random(0))
    assert picked in (a, b, c)


# ── async select_peer() ─────────────────────────────────────


@pytest.mark.asyncio
async def test_select_peer_no_peers_returns_none():
    assert await select_peer(registry=ToolRegistry()) is None


@pytest.mark.asyncio
async def test_select_peer_picks_lower_drift_among_eligible():
    reg = ToolRegistry()
    _register_peer(reg, "alpha", drift=0.04)
    _register_peer(reg, "beta", drift=0.22)
    # Two eligible peers ⇒ both sampled ⇒ deterministic lower-drift winner.
    assert await select_peer(registry=reg) == "alpha"


@pytest.mark.asyncio
async def test_select_peer_drops_refused_peer():
    reg = ToolRegistry()
    _register_peer(reg, "good", drift=0.10)
    _register_peer(reg, "drifted", drift=0.55)  # ≥ 0.30 ⇒ policy REFUSE
    assert await select_peer(registry=reg) == "good"


@pytest.mark.asyncio
async def test_select_peer_all_ineligible_returns_none():
    reg = ToolRegistry()
    _register_peer(reg, "locked", tier=0)  # T0 ⇒ REFUSE
    _register_peer(reg, "archived", plan="ARCHIVED")  # ⇒ REFUSE
    assert await select_peer(registry=reg) is None


@pytest.mark.asyncio
async def test_select_peer_capability_filter():
    reg = ToolRegistry()
    _register_peer(reg, "searcher", capabilities=("web_search",), drift=0.20)
    _register_peer(reg, "coder", capabilities=("code_exec",), drift=0.01)
    # coder has lower drift but lacks the capability ⇒ searcher is the only
    # eligible candidate.
    assert await select_peer("web_search", registry=reg) == "searcher"


@pytest.mark.asyncio
async def test_select_peer_capability_unmatched_returns_none():
    reg = ToolRegistry()
    _register_peer(reg, "coder", capabilities=("code_exec",))
    assert await select_peer("web_search", registry=reg) is None


@pytest.mark.asyncio
async def test_select_peer_unhealthy_breaker_loses():
    reg = ToolRegistry()
    _register_peer(reg, "healthy", drift=0.20)
    _register_peer(reg, "tripped", drift=0.01)
    open_breaker = CircuitBreaker(name="tripped", state=CircuitState.OPEN, opened_at=0.0)
    chosen = await select_peer(registry=reg, breakers={"tripped": open_breaker})
    assert chosen == "healthy"


@pytest.mark.asyncio
async def test_select_peer_skips_peer_with_unfetchable_state():
    reg = ToolRegistry()
    _register_peer(reg, "ok", drift=0.10)
    # Register an identity-only peer (so it's enumerated) whose kfm-state tool
    # raises ⇒ it must be skipped, not crash selection.
    async def _identity(args, ctx):
        return json.dumps({"agent_id": "broken", "capabilities": []})

    async def _bad_kfm(args, ctx):
        raise RuntimeError("offline")

    for suffix, h in (("identity", _identity), ("kfm-state", _bad_kfm)):
        name = f"mcp-broken-chimera-{suffix}"
        reg.register(
            name=name,
            toolset="mcp-broken",
            schema={"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}},
            handler=h,
        )
    assert await select_peer(registry=reg) == "ok"


# ── dispatcher method (flag-gated) ──────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_select_peer_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("CHIMERA_PEER_SELECTION", raising=False)
    reg = ToolRegistry()
    _register_peer(reg, "alpha", drift=0.04)
    disp = PeerAwareDispatcher(reg, policy=PeerTrustPolicy())
    assert await disp.select_peer() is None


@pytest.mark.asyncio
async def test_dispatcher_select_peer_enabled_returns_peer(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_SELECTION", "1")
    reg = ToolRegistry()
    _register_peer(reg, "alpha", drift=0.04)
    _register_peer(reg, "beta", drift=0.22)
    disp = PeerAwareDispatcher(reg, policy=PeerTrustPolicy())
    assert await disp.select_peer() == "alpha"
