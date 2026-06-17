"""CHIMERA_ACT_FORCE_MODEL pins ACT to a reliable Anthropic model.

The create/self-determine soaks showed ACT's cheapest-first ladder rung resolves
to an OpenRouter model that returns empty/weak completions here, so the agent
cannot converge. This knob bypasses the ladder for a specific Anthropic model.
"""

from __future__ import annotations

from chimera.core.act import _forced_anthropic_rung, _forced_rung
from chimera.providers.tiers import Provider as ProviderKind


def test_forced_known_model_reuses_tier_limits_on_anthropic():
    rung = _forced_anthropic_rung("claude-sonnet-4-6")
    assert rung.config.model_id == "claude-sonnet-4-6"
    assert rung.config.provider is ProviderKind.ANTHROPIC
    assert rung.capabilities.supports_tools is True
    # reused the SONNET tier's real rate limits (not the conservative defaults)
    assert rung.config.max_calls_per_minute > 0


def test_forced_unknown_model_gets_anthropic_defaults():
    rung = _forced_anthropic_rung("claude-some-future-model")
    assert rung.config.model_id == "claude-some-future-model"
    assert rung.config.provider is ProviderKind.ANTHROPIC
    assert rung.capabilities.supports_tools is True


def test_forced_resolves_openrouter_ladder_model_with_real_provider():
    """ADR 0183 A.1: pinning a code/sonnet ladder model resolves to its REAL
    OpenRouter rung (true provider + cost), not a synthetic Anthropic one — the
    seam the model A/B rides on."""
    qwen = _forced_rung("qwen/qwen3.7-max")  # the code-tier lead
    assert qwen.config.model_id == "qwen/qwen3.7-max"
    assert qwen.config.provider is ProviderKind.OPENROUTER
    assert qwen.config.input_cost_per_mtok > 0  # real catalog cost, not a default
    assert qwen.capabilities.supports_tools is True

    incumbent = _forced_rung("deepseek/deepseek-v4-pro")
    assert incumbent.config.model_id == "deepseek/deepseek-v4-pro"
    assert incumbent.config.provider is ProviderKind.OPENROUTER


def test_forced_unknown_id_still_falls_back_to_anthropic():
    """Back-compat: an id no ladder knows keeps the original synthetic-Anthropic
    behaviour (pin a future claude-* model)."""
    rung = _forced_rung("claude-some-future-model")
    assert rung.config.model_id == "claude-some-future-model"
    assert rung.config.provider is ProviderKind.ANTHROPIC


def test_pick_rung_honours_force_env(monkeypatch):
    from chimera.core.act import ActExecutor
    # Construct without going through __init__ provider setup.
    ap = ActExecutor.__new__(ActExecutor)
    ap._tier = "sonnet"
    monkeypatch.setenv("CHIMERA_ACT_FORCE_MODEL", "claude-opus-4-7")
    rung = ap._pick_rung(requires_tools=True)
    assert rung.config.model_id == "claude-opus-4-7"
    assert rung.config.provider is ProviderKind.ANTHROPIC


def test_pick_rung_falls_back_to_ladder_without_env(monkeypatch):
    from chimera.core.act import ActExecutor
    ap = ActExecutor.__new__(ActExecutor)
    ap._tier = "sonnet"
    monkeypatch.delenv("CHIMERA_ACT_FORCE_MODEL", raising=False)
    rung = ap._pick_rung(requires_tools=False)
    # Whatever the ladder returns — just not crashing and a real rung.
    assert rung.config.model_id
