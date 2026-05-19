"""Tests for the v2.4 cross-agent trust policy + state cache."""

from __future__ import annotations

import pytest

from chimera.a2a import (
    PeerStateCache,
    PeerTrustPolicy,
    PolicyDecision,
    is_always_allowed_peer_tool,
    peer_name_from_tool,
)


# ── tool-name helpers ───────────────────────────────────────


def test_is_always_allowed_identity():
    assert is_always_allowed_peer_tool("mcp-alpha-chimera-identity")
    assert is_always_allowed_peer_tool("mcp-beta-chimera-kfm-state")


def test_is_always_allowed_false_for_other_tools():
    assert not is_always_allowed_peer_tool("mcp-alpha-shell")
    assert not is_always_allowed_peer_tool("mcp-alpha-http_fetch")


def test_peer_name_from_tool_extracts_first_segment():
    assert peer_name_from_tool("mcp-alpha-shell") == "alpha"
    assert peer_name_from_tool("mcp-alpha-chimera-identity") == "alpha"


def test_peer_name_from_tool_returns_none_for_non_mcp():
    assert peer_name_from_tool("shell") is None
    assert peer_name_from_tool("mcp-just-prefix") == "just"


# ── PeerTrustPolicy ─────────────────────────────────────────


@pytest.fixture
def policy() -> PeerTrustPolicy:
    return PeerTrustPolicy()


def test_policy_refuses_deprecated_plan(policy):
    r = policy.evaluate({"plan_kfm_state": "DEPRECATED", "trust_tier_int": 3})
    assert r.decision is PolicyDecision.REFUSE
    assert "DEPRECATED" in r.reason


def test_policy_refuses_killed_plan(policy):
    r = policy.evaluate({"plan_kfm_state": "KILLED", "trust_tier_int": 3})
    assert r.decision is PolicyDecision.REFUSE


def test_policy_refuses_high_drift(policy):
    r = policy.evaluate(
        {"plan_kfm_state": "STABLE", "trust_tier_int": 3, "last_drift_score": 0.4}
    )
    assert r.decision is PolicyDecision.REFUSE
    assert "drift" in r.reason


def test_policy_refuses_t0_peer(policy):
    r = policy.evaluate({"plan_kfm_state": "STABLE", "trust_tier_int": 0})
    assert r.decision is PolicyDecision.REFUSE


def test_policy_degrades_t1_peer(policy):
    r = policy.evaluate({"plan_kfm_state": "STABLE", "trust_tier_int": 1})
    assert r.decision is PolicyDecision.DEGRADE


def test_policy_degrades_experimental_plan(policy):
    r = policy.evaluate({"plan_kfm_state": "EXPERIMENTAL", "trust_tier_int": 3})
    assert r.decision is PolicyDecision.DEGRADE


def test_policy_allows_stable_peer(policy):
    r = policy.evaluate(
        {"plan_kfm_state": "STABLE", "trust_tier_int": 3, "last_drift_score": 0.05}
    )
    assert r.decision is PolicyDecision.ALLOW


def test_policy_degrades_when_state_missing(policy):
    r = policy.evaluate(None)
    assert r.decision is PolicyDecision.DEGRADE


def test_policy_custom_thresholds():
    strict = PeerTrustPolicy(min_trust_tier_for_allow=4)
    r = strict.evaluate({"plan_kfm_state": "STABLE", "trust_tier_int": 3})
    assert r.decision is PolicyDecision.DEGRADE


# ── PeerStateCache ──────────────────────────────────────────


def test_cache_returns_none_before_put():
    c = PeerStateCache()
    assert c.get("alpha") is None


def test_cache_returns_stored_value_within_ttl():
    clock = iter([1.0, 1.5, 2.0])

    def _clk():
        return next(clock)

    c = PeerStateCache(ttl_seconds=5.0, clock=_clk)
    c.put("alpha", {"plan_kfm_state": "STABLE"})  # clk=1.0
    assert c.get("alpha") == {"plan_kfm_state": "STABLE"}  # clk=1.5


def test_cache_expires_past_ttl():
    times = [1.0, 1.0, 100.0]
    idx = {"i": 0}

    def _clk():
        i = idx["i"]
        idx["i"] += 1
        return times[i]

    c = PeerStateCache(ttl_seconds=5.0, clock=_clk)
    c.put("alpha", {"x": 1})  # uses time 1.0
    # First get inside TTL.
    assert c.get("alpha") == {"x": 1}  # uses 1.0
    # Second get past TTL.
    assert c.get("alpha") is None  # uses 100.0


def test_cache_invalidate_one_key():
    c = PeerStateCache()
    c.put("alpha", {"x": 1})
    c.put("beta", {"y": 2})
    c.invalidate("alpha")
    assert c.get("alpha") is None
    assert c.get("beta") == {"y": 2}


def test_cache_invalidate_all():
    c = PeerStateCache()
    c.put("alpha", {})
    c.put("beta", {})
    c.invalidate()
    assert c.get("alpha") is None
    assert c.get("beta") is None
