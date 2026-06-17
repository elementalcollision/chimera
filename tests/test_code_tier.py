"""The open-model 'code' tier (ADR 0183).

qwen3.7-max-led tool-calling code specialists with claude-opus as the trailing
safety-net, selectable but orthogonal to the haiku→sonnet→opus cost-escalation
axis. Ordered value-first per the 2026-06-15 arena (qwen led on quality at the
lowest cost; kimi-k2.7-code was dropped — tied on quality, pricier, and stalled
on the shell tool protocol). glm-5.1 → z-ai/glm-5.2 (2026-06-17 replacement).
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
        "qwen/qwen3.7-max",
        "z-ai/glm-5.2",
        "deepseek/deepseek-v4-pro",
        OPUS.openrouter_model_id or OPUS.model_id,  # claude-opus safety-net last
    ]
    # Claude-opus is the trailing safety-net rung (ADR 0072 invariant).
    assert CODE_LADDER[-1].config is OPUS
    # kimi was removed from the tier (2026-06-17).
    assert all("kimi" not in (r.config.model_id or "") for r in CODE_LADDER)


def test_code_tier_all_tool_capable():
    assert all(r.capabilities.supports_tools for r in CODE_LADDER)


def test_code_tier_leads_with_qwen():
    # select_rung walks first-capable; qwen3.7-max is the value-first lead.
    assert select_rung("code").config.model_id == "qwen/qwen3.7-max"


def test_qwen_resolvable_by_alias():
    assert resolve_rung("qwen3.7-max").config.model_id == "qwen/qwen3.7-max"


def test_code_tier_outside_escalation_axis():
    # The cost-escalation tiers stay exactly haiku/sonnet/opus; `code` is a
    # selectable peer ladder, not part of MODEL_TIERS.
    assert set(MODEL_TIERS) == {"haiku", "sonnet", "opus"}


def test_code_tier_escalation_walk():
    rungs = [r.config.model_id for r in eligible_rungs("code", requires_tools=True)]
    assert rungs[0] == "qwen/qwen3.7-max"
    assert rungs[-1] == OPUS.model_id
