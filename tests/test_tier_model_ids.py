"""tiers.tier_model_ids — model ids of a tier ladder in escalation order (spec 08)."""

from __future__ import annotations

import pytest

from chimera.providers.tiers import CODE_LADDER, TIER_LADDERS, tier_model_ids


def test_code_ladder_ids_in_escalation_order():
    # Derive expected from CODE_LADDER so the test can't drift if the ladder changes.
    assert tier_model_ids("code") == [r.config.model_id for r in CODE_LADDER]
    ids = tier_model_ids("code")
    assert len(ids) >= 2  # cheapest-first rung + a safety-net rung


def test_every_tier_resolves():
    for tier in TIER_LADDERS:
        assert tier_model_ids(tier) == [r.config.model_id for r in TIER_LADDERS[tier]]


def test_unknown_tier_raises():
    with pytest.raises(ValueError, match="unknown tier"):
        tier_model_ids("nope")
