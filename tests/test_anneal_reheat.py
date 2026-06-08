"""Tests for ADR 0169 decorrelated reheat-on-stuck."""

from __future__ import annotations

import pytest

from chimera.providers.tiers import (
    anneal_reheat_enabled,
    decorrelated_rung_order,
    eligible_rungs,
    rung_vendor,
)


# ── flag parsing ────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_ANNEAL_REHEAT", raising=False)
    assert anneal_reheat_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "On", "yes"])
def test_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_ANNEAL_REHEAT", val)
    assert anneal_reheat_enabled() is True


# ── rung_vendor ─────────────────────────────────────────────


def test_rung_vendor_namespaces():
    rungs = {r.config.model_id: r for r in eligible_rungs("sonnet")}
    # deepseek/deepseek-v4-pro → "deepseek"
    deepseek = next(r for mid, r in rungs.items() if mid.startswith("deepseek/"))
    assert rung_vendor(deepseek) == "deepseek"
    # bare claude-* safety-net → "anthropic"
    claude = next(r for mid, r in rungs.items() if mid.startswith("claude-"))
    assert rung_vendor(claude) == "anthropic"


def test_sonnet_ladder_rungs_are_distinct_vendors():
    # The decorrelation guarantee relies on adjacent rungs being different
    # vendors — verify the ladder actually has that property.
    vendors = [rung_vendor(r) for r in eligible_rungs("sonnet")]
    assert len(vendors) == len(set(vendors))


# ── decorrelated_rung_order ─────────────────────────────────


def test_reheat_count_zero_is_byte_identical():
    base = eligible_rungs("sonnet", requires_tools=True)
    rotated = decorrelated_rung_order("sonnet", reheat_count=0, requires_tools=True)
    assert [r.config.model_id for r in rotated] == [r.config.model_id for r in base]


def test_reheat_rotates_lead_vendor():
    base = eligible_rungs("sonnet", requires_tools=True)
    r1 = decorrelated_rung_order("sonnet", reheat_count=1, requires_tools=True)
    # Lead vendor differs from the un-reheated cheapest-first lead.
    assert rung_vendor(r1[0]) != rung_vendor(base[0])
    # And it's exactly a rotation by 1.
    assert r1[0].config.model_id == base[1].config.model_id


def test_successive_reheats_give_distinct_leads():
    leads = {
        decorrelated_rung_order("sonnet", reheat_count=k, requires_tools=True)[0]
        .config.model_id
        for k in range(1, 4)
    }
    # Three successive reheats ⇒ three different lead models.
    assert len(leads) == 3


def test_rotation_preserves_all_rungs():
    base = {r.config.model_id for r in eligible_rungs("sonnet", requires_tools=True)}
    rotated = {
        r.config.model_id
        for r in decorrelated_rung_order("sonnet", reheat_count=3, requires_tools=True)
    }
    assert rotated == base


def test_reheat_count_wraps_modulo():
    n = len(eligible_rungs("sonnet", requires_tools=True))
    full = decorrelated_rung_order("sonnet", reheat_count=n, requires_tools=True)
    base = eligible_rungs("sonnet", requires_tools=True)
    # A full rotation returns to the original order.
    assert [r.config.model_id for r in full] == [r.config.model_id for r in base]


def test_negative_reheat_is_unrotated():
    base = eligible_rungs("opus", requires_tools=True)
    out = decorrelated_rung_order("opus", reheat_count=-1, requires_tools=True)
    assert [r.config.model_id for r in out] == [r.config.model_id for r in base]


def test_requires_tools_filter_respected():
    out = decorrelated_rung_order("haiku", reheat_count=1, requires_tools=True)
    assert all(r.capabilities.supports_tools for r in out)
