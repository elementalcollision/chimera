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
    OpenAICompatibleProvider,
    OpenRouterProvider,
    ProviderKind,
    SakanaProvider,
    get_provider,
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


def test_opus_ladder_inverted_in_v4_53():
    """v4.53 (ADR 0072): the v4.8 ordering put Anthropic OPUS first;
    after the 2026-05-19 cost burn we inverted the ladder so the
    cheapest qualifying rung (deepseek-v4-pro) is the default and
    claude-opus-4-7 is the last-rung safety net. This is the
    direction that ``select_rung('opus')`` actually picks."""
    assert TIER_LADDERS["opus"][0].config.model_id == "deepseek/deepseek-v4-pro"
    assert TIER_LADDERS["opus"][-1].config is OPUS


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


# ── Shared AsyncClient lifecycle (offline) ───────────────────


@pytest.mark.asyncio
async def test_openrouter_provider_reuses_single_asyncclient(monkeypatch):
    """Provider must reuse one ``httpx.AsyncClient`` across calls.

    Per-call ``async with httpx.AsyncClient`` accumulates anyio-backend
    teardown state on Python 3.14 and wedges the persistent loop after
    enough cycles. This was the F2 LoCoMo full-corpus deadlock at the
    conv-26 → conv-30 boundary (~5th conversation, hundreds of calls
    in). See mind/research/f2-cross-conv-deadlock-2026-05-27.md.
    """
    import httpx

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    provider = OpenRouterProvider()
    client_a = await provider._get_client()
    client_b = await provider._get_client()
    assert client_a is client_b
    assert isinstance(client_a, httpx.AsyncClient)
    await provider.aclose()


@pytest.mark.asyncio
async def test_openrouter_complete_with_tools_does_not_open_per_call_clients(monkeypatch):
    """N successive ``complete_with_tools`` calls must share one
    underlying ``httpx.AsyncClient`` instance.

    A regression where someone reintroduces ``async with
    httpx.AsyncClient(...) as client`` inside the request method
    reopens the F2 cross-conv deadlock — this test fails that change
    by asserting the constructor fires exactly once.
    """
    import httpx

    from chimera.providers import Message

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    construct_count = 0
    real_async_client = httpx.AsyncClient

    def _counting_async_client(*args, **kwargs):
        nonlocal construct_count
        construct_count += 1
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _counting_async_client)

    async def _fake_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider = OpenRouterProvider()
    # Pre-seed the client with a MockTransport so no real network fires.
    provider._client = real_async_client(
        timeout=provider._timeout,
        headers=provider._headers,
        transport=httpx.MockTransport(_fake_handler),
    )
    provider._client_loop = __import__("asyncio").get_running_loop()
    construct_count = 0  # reset after our pre-seed

    for _ in range(5):
        resp = await provider.complete_with_tools(
            messages=[Message.user("hi")],
            model_id="x",
            tools=[],
            max_tokens=8,
        )
        assert resp.text == "ok"
    assert construct_count == 0, (
        f"AsyncClient was reconstructed {construct_count}× across 5 calls — "
        "regression: per-call AsyncClient pattern reintroduced."
    )
    await provider.aclose()


async def test_openrouter_captures_reasoning_when_content_empty(monkeypatch):
    """B.4j: a reasoning model can surface empty `content` + a `reasoning` trace (budget
    spent on hidden reasoning). The provider must capture `reasoning` so the guardrail
    eval can fall back to it instead of grading the probe ERROR."""
    import asyncio

    import httpx

    from chimera.providers import Message

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    async def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{
                "message": {"content": "", "reasoning": "I will refuse this request."},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 50},
        })

    provider = OpenRouterProvider()
    provider._client = httpx.AsyncClient(
        timeout=provider._timeout, headers=provider._headers,
        transport=httpx.MockTransport(_handler),
    )
    provider._client_loop = asyncio.get_running_loop()
    resp = await provider.complete_with_tools(
        messages=[Message.user("hi")], model_id="x", tools=[], max_tokens=8,
    )
    assert resp.text == "" and resp.reasoning == "I will refuse this request."
    await provider.aclose()


@pytest.mark.asyncio
async def test_openrouter_provider_rebinds_client_on_loop_change(monkeypatch):
    """If a provider instance is reused across distinct loops (tests do
    this), ``_get_client`` must drop and recreate so the client is
    bound to the current running loop. Production has one persistent
    loop, so this branch is exercised primarily by tests; the contract
    keeps us safe if a future caller spins up its own loop.
    """
    import asyncio
    import httpx

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    provider = OpenRouterProvider()
    c1 = await provider._get_client()

    # Simulate a different loop by mutating the stored reference.
    fake_other = asyncio.new_event_loop()
    try:
        provider._client_loop = fake_other
        c2 = await provider._get_client()
        assert c2 is not c1
        assert provider._client_loop is asyncio.get_running_loop()
        assert provider._client_loop is not fake_other
        assert isinstance(c2, httpx.AsyncClient)
    finally:
        fake_other.close()
        await provider.aclose()


# ── Sakana Fugu provider (offline) ───────────────────────────


def test_sakana_provider_requires_key(monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    monkeypatch.delenv("FUGU_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        SakanaProvider()


def test_sakana_provider_accepts_fugu_key_fallback(monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    monkeypatch.setenv("FUGU_API_KEY", "k")
    p = SakanaProvider()
    assert p.name == "sakana"
    assert p._url == "https://api.sakana.ai/v1/chat/completions"


def test_sakana_is_openai_compatible(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    assert isinstance(SakanaProvider(), OpenAICompatibleProvider)


@pytest.mark.parametrize("override,expected", [
    ("https://api.sakana.ai", "https://api.sakana.ai/v1/chat/completions"),
    ("https://api.sakana.ai/", "https://api.sakana.ai/v1/chat/completions"),
    ("https://api.sakana.ai/v1", "https://api.sakana.ai/v1/chat/completions"),
    ("https://proxy.internal/v1/chat/completions",
     "https://proxy.internal/v1/chat/completions"),
])
def test_sakana_base_url_override_normalized(monkeypatch, override, expected):
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    monkeypatch.setenv("SAKANA_BASE_URL", override)
    assert SakanaProvider()._url == expected


@pytest.mark.asyncio
async def test_sakana_posts_to_sakana_endpoint(monkeypatch):
    import asyncio
    import json as _json

    import httpx

    from chimera.providers import Message

    monkeypatch.setenv("SAKANA_API_KEY", "k")
    seen: dict = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = _json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    provider = SakanaProvider()
    provider._client = httpx.AsyncClient(
        timeout=provider._timeout, headers=provider._headers,
        transport=httpx.MockTransport(_handler),
    )
    provider._client_loop = asyncio.get_running_loop()
    resp = await provider.complete_with_tools(
        messages=[Message.user("hi")], model_id="fugu", tools=[], max_tokens=8,
    )
    assert resp.text == "pong"
    assert resp.provider == "sakana"
    assert seen["url"] == "https://api.sakana.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "fugu"
    await provider.aclose()


def test_sakana_default_timeout_is_generous(monkeypatch):
    # Fugu-ultra is a slow ensemble; the default must exceed a normal LLM timeout.
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    monkeypatch.delenv("SAKANA_TIMEOUT", raising=False)
    assert SakanaProvider()._timeout == 180.0


def test_sakana_timeout_env_override(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    monkeypatch.setenv("SAKANA_TIMEOUT", "300")
    assert SakanaProvider()._timeout == 300.0


def test_sakana_explicit_timeout_wins(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    monkeypatch.setenv("SAKANA_TIMEOUT", "300")
    assert SakanaProvider(timeout=45.0)._timeout == 45.0


def test_get_provider_factory(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(get_provider("sakana"), SakanaProvider)
    assert isinstance(get_provider("openrouter"), OpenRouterProvider)
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
    assert isinstance(get_provider("SAKANA"), SakanaProvider)  # case-insensitive
    with pytest.raises(ValueError):
        get_provider("bogus")


def test_openrouter_is_openai_compatible_after_refactor(monkeypatch):
    """Refactor safety: OpenRouter is now an OpenAICompatibleProvider subclass and
    still targets the OpenRouter endpoint with its name preserved."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    p = OpenRouterProvider()
    assert isinstance(p, OpenAICompatibleProvider)
    assert p._url == "https://openrouter.ai/api/v1/chat/completions"
    assert p.name == "openrouter"


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


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (os.environ.get("SAKANA_API_KEY") or os.environ.get("FUGU_API_KEY")),
    reason="SAKANA_API_KEY / FUGU_API_KEY not set",
)
async def test_sakana_live_ping():
    """Test #1 (liveness): a real one-token round-trip against Fugu. Gated on the
    key so CI skips it; run locally after placing SAKANA_API_KEY in .env."""
    provider = SakanaProvider()
    chunks = []
    async for chunk in provider.stream(
        [ChatMessage(role="user", content="Say 'pong' and nothing else.")],
        model_id="fugu",
        max_tokens=128,
    ):
        chunks.append(chunk)
    text = "".join(c.text for c in chunks)
    assert "pong" in text.lower()
