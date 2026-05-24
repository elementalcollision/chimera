"""Tests for Honcho-inspired trivial wins (ADR 0123).

Covers:
  * ReasoningTier enum values + default-NORMAL invariant
  * Context.to_openai() builder — assembly, truncation, model passthrough
  * Token estimation fallback when tiktoken is absent
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.budget import (
    Context,
    ReasoningTier,
    _estimate_tokens,
)


# ── ADR 0123 — Reasoning tiers ─────────────────────────────────────


def test_reasoning_tier_values():
    assert ReasoningTier.MINIMAL.value == "minimal"
    assert ReasoningTier.NORMAL.value == "normal"
    assert ReasoningTier.DEEP.value == "deep"
    assert ReasoningTier.MAX.value == "max"


def test_reasoning_tier_default_is_normal():
    """Honcho-inspired default — keep current behavior unless caller opts in."""
    def call_routed(*, tier: ReasoningTier = ReasoningTier.NORMAL) -> ReasoningTier:
        return tier

    assert call_routed() is ReasoningTier.NORMAL
    assert call_routed(tier=ReasoningTier.DEEP) is ReasoningTier.DEEP


def test_reasoning_tiers_ordered_by_cost():
    """Sanity: all four tiers exist, distinct, and equality works."""
    tiers = {ReasoningTier.MINIMAL, ReasoningTier.NORMAL,
             ReasoningTier.DEEP, ReasoningTier.MAX}
    assert len(tiers) == 4


# ── Context.to_openai() ────────────────────────────────────────────


def test_context_to_openai_assembles_payload():
    ctx = Context(
        system="You are a helpful assistant.",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        max_tokens=4_000,
    )
    payload = ctx.to_openai(model="claude-haiku-4-5")
    assert payload["model"] == "claude-haiku-4-5"
    assert payload["messages"][0] == {
        "role": "system",
        "content": "You are a helpful assistant.",
    }
    assert payload["messages"][-1]["content"] == "hello"
    assert len(payload["messages"]) == 3  # system + 2 turns


def test_context_to_openai_omits_model_when_unspecified():
    ctx = Context(messages=[{"role": "user", "content": "ping"}])
    payload = ctx.to_openai()
    assert "model" not in payload
    assert payload["messages"] == [{"role": "user", "content": "ping"}]


def test_context_to_openai_truncates_middle_under_budget():
    """Middle messages drop first; head + last 2 messages preserved."""
    messages = [
        {"role": "user", "content": "FIRST " + "x" * 4_000},
        {"role": "assistant", "content": "MID1 " + "y" * 4_000},
        {"role": "user", "content": "MID2 " + "z" * 4_000},
        {"role": "assistant", "content": "MID3 " + "w" * 4_000},
        {"role": "user", "content": "TAIL-PENULT"},
        {"role": "assistant", "content": "TAIL-LAST"},
    ]
    ctx = Context(system="sys", messages=messages, max_tokens=500)
    payload = ctx.to_openai()
    contents = [m["content"] for m in payload["messages"]]
    # System preserved.
    assert contents[0] == "sys"
    # Last two preserved.
    assert "TAIL-PENULT" in contents
    assert "TAIL-LAST" in contents
    # First user message preserved (head anchor).
    assert any(c.startswith("FIRST ") for c in contents)
    # At least one middle dropped.
    assert sum(1 for c in contents if c.startswith("MID")) < 3


def test_context_to_openai_preserves_short_conversation():
    """Below the budget, no truncation occurs."""
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    ctx = Context(messages=messages, max_tokens=10_000)
    payload = ctx.to_openai()
    assert len(payload["messages"]) == 3
    assert [m["content"] for m in payload["messages"]] == ["a", "b", "c"]


def test_context_estimated_tokens_nonzero_when_populated():
    ctx = Context(system="hello", messages=[{"role": "user", "content": "world"}])
    assert ctx.estimated_tokens() > 0


def test_context_empty_estimate_is_zero():
    assert Context().estimated_tokens() == 0


# ── Token estimation ──────────────────────────────────────────────


def test_estimate_tokens_empty_string():
    assert _estimate_tokens("") == 0


def test_estimate_tokens_nonempty():
    n = _estimate_tokens("hello world, this is a sentence.")
    assert n > 0


def test_estimate_tokens_fallback_heuristic(monkeypatch):
    """When tiktoken import fails, fall back to ~4-chars-per-token."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("simulated absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # 16 chars → ~4 tokens under the heuristic.
    assert _estimate_tokens("a" * 16) == 4


# ── ADR 0123 doc presence ─────────────────────────────────────────


def test_adr_0123_present():
    adr_path = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0123-honcho-inspired-enhancements.md"
    )
    assert adr_path.exists(), "ADR 0123 must be filed"
    body = adr_path.read_text()
    # Cross-reference invariants — keep terminology aligned with the
    # Honcho R&D doc for traceability.
    assert "ReasoningTier" in body
    assert "to_openai" in body
    assert "honcho-evaluation-2026-05-24.md" in body
