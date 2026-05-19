"""Provider abstraction tests.

Unit tests run offline; live ``ping`` tests are gated on env keys and
skipped when absent.
"""

from __future__ import annotations

import os

import pytest

from chimera.providers import (
    HAIKU,
    HAIKU_LADDER,
    MODEL_TIERS,
    OPUS,
    SONNET,
    TIER_LADDERS,
    AnthropicProvider,
    ChatMessage,
    OpenRouterProvider,
    ProviderKind,
    select_rung,
)


# ── Tier loading (offline) ───────────────────────────────────


def test_model_tiers_have_three_entries():
    assert set(MODEL_TIERS) == {"haiku", "sonnet", "opus"}


def test_anthropic_model_ids_are_current():
    assert HAIKU.model_id == "claude-haiku-4-5-20251001"
    assert SONNET.model_id == "claude-sonnet-4-6"
    assert OPUS.model_id == "claude-opus-4-7"


def test_haiku_sonnet_ladders_end_with_anthropic_safety_net():
    """Haiku + sonnet ladders end with the Anthropic model as the safety net."""
    assert TIER_LADDERS["haiku"][-1].config is HAIKU
    assert TIER_LADDERS["sonnet"][-1].config is SONNET


def test_opus_ladder_starts_with_anthropic_opus_after_v4_8():
    """v4.8: opus reordered so Anthropic is first (strongest baseline for code-gen)."""
    assert TIER_LADDERS["opus"][0].config is OPUS


def test_haiku_sonnet_ladders_start_with_openrouter():
    """Cheapest-first: OpenRouter rungs precede Anthropic on haiku + sonnet."""
    for tier_name in ("haiku", "sonnet"):
        ladder = TIER_LADDERS[tier_name]
        assert ladder[0].config.provider is ProviderKind.OPENROUTER, (
            f"{tier_name} ladder should start with an OpenRouter rung"
        )


def test_select_rung_returns_cheapest_by_default():
    rung = select_rung("haiku")
    assert rung is TIER_LADDERS["haiku"][0]


def test_select_rung_requires_tools_skips_incapable_rungs():
    # All MVP rungs claim supports_tools=True; this still exercises the path.
    rung = select_rung("sonnet", requires_tools=True)
    assert rung.capabilities.supports_tools is True


def test_select_rung_unknown_tier_raises():
    with pytest.raises(ValueError):
        select_rung("legendary")


# ── Provider construction (offline) ──────────────────────────


def test_anthropic_provider_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


def test_openrouter_provider_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider()


# ── Live ping (gated on env) ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_anthropic_live_ping():
    provider = AnthropicProvider()
    chunks = []
    async for chunk in provider.stream(
        [ChatMessage(role="user", content="Say 'pong' and nothing else.")],
        model_id=HAIKU.model_id,
        max_tokens=128,
    ):
        chunks.append(chunk)
    text = "".join(c.text for c in chunks)
    assert "pong" in text.lower()
    assert chunks[-1].finish_reason is not None


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
async def test_openrouter_live_ping():
    provider = OpenRouterProvider()
    # Use the first native OpenRouter rung (not the Anthropic mirror — those
    # `anthropic/claude-*` IDs need format verification against OpenRouter's
    # current model registry; see TODO in tiers.py).
    first_or_rung = next(
        r for r in HAIKU_LADDER if r.config.provider is ProviderKind.OPENROUTER
    )
    chunks = []
    async for chunk in provider.stream(
        [ChatMessage(role="user", content="Say 'pong' and nothing else.")],
        model_id=first_or_rung.config.openrouter_model_id,
        max_tokens=128,
    ):
        chunks.append(chunk)
    text = "".join(c.text for c in chunks)
    assert "pong" in text.lower()
    assert chunks[-1].finish_reason is not None
