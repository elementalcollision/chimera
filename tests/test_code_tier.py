"""The open-model 'code' tier (ADR 0183, operator-specified 2026-06-15).

Kimi-led tool-calling code specialists with claude-opus as the trailing
safety-net, selectable but orthogonal to the haiku→sonnet→opus cost-
escalation axis.
"""

from __future__ import annotations

from chimera.providers import (
    CODE_LADDER,
    MODEL_TIERS,
    OPUS,
    TIER_LADDERS,
)
from chimera.providers.tiers import eligible_rungs, resolve_rung, select_rung


def test_code_tier_registered():
    assert "code" in TIER_LADDERS
    assert TIER_LADDERS["code"] is CODE_LADDER


def test_code_tier_composition_and_order():
    ids = [r.config.openrouter_model_id for r in CODE_LADDER]
    assert ids == [
        "moonshotai/kimi-k2.7-code",
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.1",
        "qwen/qwen3.7-max",
        OPUS.openrouter_model_id or OPUS.model_id,  # claude-opus safety-net last
    ]
    # Claude-opus is the trailing safety-net rung (ADR 0072 invariant).
    assert CODE_LADDER[-1].config is OPUS


def test_code_tier_all_tool_capable():
    assert all(r.capabilities.supports_tools for r in CODE_LADDER)


def test_code_tier_leads_with_kimi():
    # select_rung walks cheapest/first-capable; the operator ordered kimi first.
    assert select_rung("code").config.model_id == "moonshotai/kimi-k2.7-code"


def test_kimi_resolvable_by_alias():
    assert resolve_rung("kimi-k2.7-code").config.model_id == "moonshotai/kimi-k2.7-code"


def test_code_tier_outside_escalation_axis():
    # The cost-escalation tiers stay exactly haiku/sonnet/opus; `code` is a
    # selectable peer ladder, not part of MODEL_TIERS.
    assert set(MODEL_TIERS) == {"haiku", "sonnet", "opus"}


def test_code_tier_escalation_walk():
    rungs = [r.config.model_id for r in eligible_rungs("code", requires_tools=True)]
    assert rungs[0] == "moonshotai/kimi-k2.7-code"
    assert rungs[-1] == OPUS.model_id
