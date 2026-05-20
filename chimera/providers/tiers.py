"""Model tier definitions + tier ladders.

Ported from leonardo-daemon/daemon/config.py (NVIDIA-free profile) per
ADR 0001 §"Model tier ladder + routing".

MVP simplifications:
- No voice_only rungs (Leonardo's voice system is inspiration-only per
  user decision; ADR 0001 §"Voice / prompt style").
- No witness / garden / experimental tier variants.
- Anthropic model IDs current as of 2026-05: opus-4-7, sonnet-4-6,
  haiku-4-5-20251001.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a single model."""

    model_id: str
    max_calls_per_minute: int
    max_calls_per_hour: int
    max_calls_per_day: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    provider: Provider = Provider.ANTHROPIC
    openrouter_model_id: str = ""


@dataclass(frozen=True)
class ModelCapabilities:
    """Declared capabilities of a ladder rung."""

    supports_tools: bool = False
    supports_json_mode: bool = False
    supports_vision: bool = False
    reasoning_optimized: bool = False
    context_tokens: int = 200_000


@dataclass(frozen=True)
class LadderRung:
    """One rung in a tier ladder."""

    config: ModelConfig
    capabilities: ModelCapabilities

    @property
    def label(self) -> str:
        return self.config.model_id


# ── Anthropic tiers (safety-net rungs) ─────────────────────
#
# TODO: The ``openrouter_model_id`` mirrors below (``anthropic/claude-*``)
# need format verification against OpenRouter's current model registry.
# 2026-05-18 live test showed ``anthropic/claude-haiku-4-5-20251001`` is
# rejected with "not a valid model ID". The date-suffix variant is likely
# the issue; OpenRouter probably wants ``anthropic/claude-haiku-4.5`` or
# similar. Verify before relying on the Anthropic-via-OpenRouter fallback.

HAIKU = ModelConfig(
    model_id="claude-haiku-4-5-20251001",
    max_calls_per_minute=20,
    max_calls_per_hour=200,
    max_calls_per_day=10_000,
    input_cost_per_mtok=0.80,
    output_cost_per_mtok=4.00,
    openrouter_model_id="anthropic/claude-haiku-4-5-20251001",
)

SONNET = ModelConfig(
    model_id="claude-sonnet-4-6",
    max_calls_per_minute=5,
    max_calls_per_hour=30,
    max_calls_per_day=200,
    input_cost_per_mtok=3.00,
    output_cost_per_mtok=15.00,
    openrouter_model_id="anthropic/claude-sonnet-4-6",
)

OPUS = ModelConfig(
    model_id="claude-opus-4-7",
    max_calls_per_minute=1,
    max_calls_per_hour=4,
    max_calls_per_day=20,
    input_cost_per_mtok=15.00,
    output_cost_per_mtok=75.00,
    openrouter_model_id="anthropic/claude-opus-4-7",
)

MODEL_TIERS: dict[str, ModelConfig] = {"haiku": HAIKU, "sonnet": SONNET, "opus": OPUS}


# ── OpenRouter ladder rungs (cheapest → safety-net) ────────

LADDER_DEEPSEEK_V4_FLASH = ModelConfig(
    model_id="deepseek/deepseek-v4-flash",
    max_calls_per_minute=20,
    max_calls_per_hour=200,
    max_calls_per_day=10_000,
    input_cost_per_mtok=0.14,
    output_cost_per_mtok=0.28,
    provider=Provider.OPENROUTER,
    openrouter_model_id="deepseek/deepseek-v4-flash",
)

LADDER_QWEN36_FLASH = ModelConfig(
    model_id="qwen/qwen3.6-flash",
    max_calls_per_minute=20,
    max_calls_per_hour=200,
    max_calls_per_day=10_000,
    input_cost_per_mtok=0.25,
    output_cost_per_mtok=1.50,
    provider=Provider.OPENROUTER,
    openrouter_model_id="qwen/qwen3.6-flash",
)

LADDER_DEEPSEEK_V4_PRO = ModelConfig(
    model_id="deepseek/deepseek-v4-pro",
    max_calls_per_minute=10,
    max_calls_per_hour=100,
    max_calls_per_day=2_000,
    input_cost_per_mtok=0.435,
    output_cost_per_mtok=0.87,
    provider=Provider.OPENROUTER,
    openrouter_model_id="deepseek/deepseek-v4-pro",
)

LADDER_QWEN35_PLUS = ModelConfig(
    model_id="qwen/qwen3.5-plus-20260420",
    max_calls_per_minute=10,
    max_calls_per_hour=100,
    max_calls_per_day=2_000,
    input_cost_per_mtok=0.40,
    output_cost_per_mtok=2.40,
    provider=Provider.OPENROUTER,
    openrouter_model_id="qwen/qwen3.5-plus-20260420",
)


# ── Tier ladders (Leonardo NVIDIA-free shape) ──────────────

HAIKU_LADDER: list[LadderRung] = [
    LadderRung(
        config=LADDER_DEEPSEEK_V4_FLASH,
        capabilities=ModelCapabilities(
            supports_tools=True, supports_json_mode=True, context_tokens=1_048_576
        ),
    ),
    LadderRung(
        config=LADDER_QWEN36_FLASH,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            context_tokens=1_000_000,
        ),
    ),
    LadderRung(
        config=HAIKU,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            context_tokens=200_000,
        ),
    ),
]

SONNET_LADDER: list[LadderRung] = [
    LadderRung(
        config=LADDER_DEEPSEEK_V4_PRO,
        capabilities=ModelCapabilities(
            supports_tools=True, supports_json_mode=True, context_tokens=1_048_576
        ),
    ),
    LadderRung(
        config=LADDER_QWEN35_PLUS,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            context_tokens=1_000_000,
        ),
    ),
    LadderRung(
        config=SONNET,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            context_tokens=200_000,
        ),
    ),
]

LADDER_OPENAI_GPT5_PRO = ModelConfig(
    model_id="openai/gpt-5-pro",
    max_calls_per_minute=5,
    max_calls_per_hour=60,
    max_calls_per_day=500,
    input_cost_per_mtok=2.50,
    output_cost_per_mtok=10.00,
    provider=Provider.OPENROUTER,
    openrouter_model_id="openai/gpt-5-pro",
)

LADDER_GEMINI_3_PRO = ModelConfig(
    model_id="google/gemini-3-pro",
    max_calls_per_minute=15,
    max_calls_per_hour=300,
    max_calls_per_day=3_000,
    input_cost_per_mtok=1.25,
    output_cost_per_mtok=5.00,
    provider=Provider.OPENROUTER,
    openrouter_model_id="google/gemini-3-pro",
)


# OPUS_LADDER (v4.53): Deepseek-v4-pro FIRST. Pre-v4.53 had opus first
# ("strongest baseline for code generation"), but the 2026-05-19 overnight
# run burned $229 in 2h on 801 opus calls when escalation memory promoted
# a fanout-heavy task to tier="opus" — which under the old ordering meant
# claude-opus-4-7 by default. See [ADR 0072](./0072-cost-runaway-guards.md).
# The new ordering treats opus as a *reasoning capability tier*, not an
# "always reach for claude-opus" tier. Deepseek-v4-pro at $0.435/$0.87 per
# Mtok handles 80% of opus-tier work for 1/34th the cost; claude-opus
# remains the last-rung safety net when cheaper rungs genuinely fail.
# Cross-witness critique (ADR 0031) still uses per-rung aliases
# (``witnesses=("claude-opus-4-7", ...)``) so disagreement room is unchanged.
OPUS_LADDER: list[LadderRung] = [
    LadderRung(
        config=LADDER_DEEPSEEK_V4_PRO,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            reasoning_optimized=True,
            context_tokens=1_048_576,
        ),
    ),
    LadderRung(
        config=LADDER_GEMINI_3_PRO,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            reasoning_optimized=True,
            context_tokens=2_000_000,
        ),
    ),
    LadderRung(
        config=LADDER_OPENAI_GPT5_PRO,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            reasoning_optimized=True,
            context_tokens=400_000,
        ),
    ),
    LadderRung(
        config=OPUS,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_json_mode=True,
            supports_vision=True,
            reasoning_optimized=True,
            context_tokens=200_000,
        ),
    ),
]

TIER_LADDERS: dict[str, list[LadderRung]] = {
    "haiku": HAIKU_LADDER,
    "sonnet": SONNET_LADDER,
    "opus": OPUS_LADDER,
}


def _all_rungs() -> list[LadderRung]:
    """Deduplicated flat list of every rung across every tier ladder."""
    seen: dict[str, LadderRung] = {}
    for ladder in TIER_LADDERS.values():
        for r in ladder:
            seen.setdefault(r.config.model_id, r)
    return list(seen.values())


def _alias_for(rung: LadderRung) -> str:
    """Short, model-only name. 'openai/gpt-5-pro' → 'gpt-5-pro';
    'claude-opus-4-7' → 'claude-opus-4-7' (no provider prefix)."""
    mid = rung.config.model_id
    return mid.split("/", 1)[1] if "/" in mid else mid


def resolve_rung(name: str) -> LadderRung:
    """Resolve a name into a single rung.

    - Tier name (``"haiku"`` / ``"sonnet"`` / ``"opus"``) → that tier's
      cheapest rung (matches :func:`select_rung`).
    - Per-rung alias (``"gpt-5-pro"``, ``"gemini-3-pro"``,
      ``"deepseek-v4-pro"``, ``"claude-opus-4-7"``, …) → the matching
      rung from any ladder.

    Per-rung aliases let cross-witness callers say
    ``witnesses=("claude-opus-4-7", "gpt-5-pro", "gemini-3-pro")``
    instead of being limited to tier-level routing.
    """
    if name in TIER_LADDERS:
        return select_rung(name)
    for rung in _all_rungs():
        if _alias_for(rung) == name:
            return rung
        if rung.config.model_id == name:
            return rung
    raise ValueError(
        f"unknown rung name {name!r}; valid tiers: {list(TIER_LADDERS)}; "
        f"or pass a model alias like 'gpt-5-pro' / 'claude-opus-4-7'"
    )


def eligible_rungs(
    tier: str, *, requires_tools: bool = False, prefer_cheapest: bool = True,
) -> list[LadderRung]:
    """Return all ladder rungs satisfying the request, in escalation order.

    Used by the ACT executor (v3.11+) to walk down the ladder when a rung
    exhausts its retries. Cheapest-first matches :func:`select_rung`.
    """
    if tier not in TIER_LADDERS:
        raise ValueError(f"unknown tier: {tier!r}; valid: {list(TIER_LADDERS)}")
    rungs = TIER_LADDERS[tier]
    ordered = rungs if prefer_cheapest else list(reversed(rungs))
    return [r for r in ordered if not requires_tools or r.capabilities.supports_tools]


def select_rung(tier: str, *, requires_tools: bool = False, prefer_cheapest: bool = True) -> LadderRung:
    """Pick a rung from a tier ladder.

    MVP heuristic: walk the ladder cheapest-first, return the first rung
    whose capabilities satisfy the request. The Reggio-style adaptive
    policy (per-rung outcome tracking) is a follow-up.
    """
    if tier not in TIER_LADDERS:
        raise ValueError(f"unknown tier: {tier!r}; valid: {list(TIER_LADDERS)}")
    rungs = TIER_LADDERS[tier]
    candidates = rungs if prefer_cheapest else list(reversed(rungs))
    for rung in candidates:
        if requires_tools and not rung.capabilities.supports_tools:
            continue
        return rung
    raise RuntimeError(f"no rung in tier {tier!r} satisfies requires_tools={requires_tools}")
