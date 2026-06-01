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
# 2026-06 refresh: the ``openrouter_model_id`` mirrors are now the dotted
# catalog forms (``anthropic/claude-haiku-4.5`` / ``-sonnet-4.6`` / ``-opus-4.7``),
# live-verified against OpenRouter. The prior date-suffix IDs
# (``anthropic/claude-haiku-4-5-20251001``) were rejected as invalid — TODO
# resolved. See mind/research/model-tier-reeval-2026-06-01.md.

HAIKU = ModelConfig(
    model_id="claude-haiku-4-5-20251001",
    max_calls_per_minute=20,
    max_calls_per_hour=200,
    max_calls_per_day=10_000,
    input_cost_per_mtok=0.80,
    output_cost_per_mtok=4.00,
    openrouter_model_id="anthropic/claude-haiku-4.5",
)

SONNET = ModelConfig(
    model_id="claude-sonnet-4-6",
    max_calls_per_minute=5,
    max_calls_per_hour=30,
    max_calls_per_day=200,
    input_cost_per_mtok=3.00,
    output_cost_per_mtok=15.00,
    openrouter_model_id="anthropic/claude-sonnet-4.6",
)

OPUS = ModelConfig(
    model_id="claude-opus-4-7",
    max_calls_per_minute=1,
    max_calls_per_hour=4,
    max_calls_per_day=20,
    input_cost_per_mtok=15.00,
    output_cost_per_mtok=75.00,
    openrouter_model_id="anthropic/claude-opus-4.7",
)

MODEL_TIERS: dict[str, ModelConfig] = {"haiku": HAIKU, "sonnet": SONNET, "opus": OPUS}


# ── OpenRouter ladder rungs (2026-06 refresh) ──────────────
#
# Re-evaluated live against the OpenRouter catalog (mind/research/
# model-tier-reeval-2026-06-01.md). Replaces the stale set: google/gemini-3-pro
# (invalid 400), openai/gpt-5-pro (superseded, priciest gpt-5), deepseek-v4-flash
# / qwen3.6 / qwen3.5-plus. All rungs below are live-verified tool-capable.
# NOTE: several are reasoning-optimized — callers MUST budget adequate output
# tokens (a tiny max_tokens starves them to empty output; see the re-eval doc).

# Cheap, reliable workhorses (haiku tier).
LADDER_GPT5_NANO = ModelConfig(
    model_id="openai/gpt-5-nano", max_calls_per_minute=20, max_calls_per_hour=400,
    max_calls_per_day=10_000, input_cost_per_mtok=0.05, output_cost_per_mtok=0.40,
    provider=Provider.OPENROUTER, openrouter_model_id="openai/gpt-5-nano",
)
LADDER_QWEN3_235B = ModelConfig(
    model_id="qwen/qwen3-235b-a22b-2507", max_calls_per_minute=20,
    max_calls_per_hour=400, max_calls_per_day=10_000, input_cost_per_mtok=0.071,
    output_cost_per_mtok=0.10, provider=Provider.OPENROUTER,
    openrouter_model_id="qwen/qwen3-235b-a22b-2507",
)

# ACT spread (sonnet tier) — operator-selected diverse, cross-vendor build models.
LADDER_DEEPSEEK_V4_PRO = ModelConfig(
    model_id="deepseek/deepseek-v4-pro", max_calls_per_minute=10,
    max_calls_per_hour=100, max_calls_per_day=2_000, input_cost_per_mtok=0.435,
    output_cost_per_mtok=0.87, provider=Provider.OPENROUTER,
    openrouter_model_id="deepseek/deepseek-v4-pro",
)
LADDER_MINIMAX_M3 = ModelConfig(
    model_id="minimax/minimax-m3", max_calls_per_minute=10, max_calls_per_hour=100,
    max_calls_per_day=2_000, input_cost_per_mtok=0.30, output_cost_per_mtok=1.20,
    provider=Provider.OPENROUTER, openrouter_model_id="minimax/minimax-m3",
)
LADDER_GLM_5_1 = ModelConfig(
    model_id="z-ai/glm-5.1", max_calls_per_minute=10, max_calls_per_hour=100,
    max_calls_per_day=2_000, input_cost_per_mtok=0.98, output_cost_per_mtok=3.08,
    provider=Provider.OPENROUTER, openrouter_model_id="z-ai/glm-5.1",
)
LADDER_QWEN37_MAX = ModelConfig(
    model_id="qwen/qwen3.7-max", max_calls_per_minute=10, max_calls_per_hour=100,
    max_calls_per_day=2_000, input_cost_per_mtok=1.25, output_cost_per_mtok=3.75,
    provider=Provider.OPENROUTER, openrouter_model_id="qwen/qwen3.7-max",
)
LADDER_MISTRAL_MEDIUM = ModelConfig(
    model_id="mistralai/mistral-medium-3-5", max_calls_per_minute=10,
    max_calls_per_hour=100, max_calls_per_day=2_000, input_cost_per_mtok=1.50,
    output_cost_per_mtok=7.50, provider=Provider.OPENROUTER,
    openrouter_model_id="mistralai/mistral-medium-3-5",
)
LADDER_GEMINI_31_PRO = ModelConfig(
    model_id="google/gemini-3.1-pro-preview", max_calls_per_minute=15,
    max_calls_per_hour=300, max_calls_per_day=3_000, input_cost_per_mtok=2.00,
    output_cost_per_mtok=12.00, provider=Provider.OPENROUTER,
    openrouter_model_id="google/gemini-3.1-pro-preview",
)

# Specialists (opus tier) — code + tool-optimized.
LADDER_GPT5_CODEX_MAX = ModelConfig(
    model_id="openai/gpt-5.1-codex-max", max_calls_per_minute=5,
    max_calls_per_hour=60, max_calls_per_day=500, input_cost_per_mtok=1.25,
    output_cost_per_mtok=10.00, provider=Provider.OPENROUTER,
    openrouter_model_id="openai/gpt-5.1-codex-max",
)
LADDER_GEMINI_31_CUSTOMTOOLS = ModelConfig(
    model_id="google/gemini-3.1-pro-preview-customtools", max_calls_per_minute=15,
    max_calls_per_hour=300, max_calls_per_day=3_000, input_cost_per_mtok=2.00,
    output_cost_per_mtok=12.00, provider=Provider.OPENROUTER,
    openrouter_model_id="google/gemini-3.1-pro-preview-customtools",
)


# ── Tier ladders (cheapest → safety-net) ───────────────────
_REASON = dict(supports_tools=True, supports_json_mode=True, reasoning_optimized=True)
_REASON_BIG = dict(_REASON, context_tokens=1_048_576)

HAIKU_LADDER: list[LadderRung] = [
    LadderRung(LADDER_GPT5_NANO, ModelCapabilities(**dict(_REASON, context_tokens=400_000))),
    LadderRung(LADDER_QWEN3_235B, ModelCapabilities(supports_tools=True, supports_json_mode=True, context_tokens=262_144)),
    LadderRung(HAIKU, ModelCapabilities(supports_tools=True, supports_json_mode=True, supports_vision=True, context_tokens=200_000)),
]

# SONNET_LADDER = the ACT build-loop spread (operator-selected, diverse vendors).
SONNET_LADDER: list[LadderRung] = [
    LadderRung(LADDER_DEEPSEEK_V4_PRO, ModelCapabilities(**_REASON_BIG)),
    LadderRung(LADDER_MINIMAX_M3, ModelCapabilities(**_REASON_BIG)),
    LadderRung(LADDER_GLM_5_1, ModelCapabilities(supports_tools=True, supports_json_mode=True, context_tokens=202_752)),
    LadderRung(LADDER_QWEN37_MAX, ModelCapabilities(**dict(_REASON, context_tokens=1_000_000))),
    LadderRung(LADDER_MISTRAL_MEDIUM, ModelCapabilities(supports_tools=True, supports_json_mode=True, context_tokens=262_144)),
    LadderRung(LADDER_GEMINI_31_PRO, ModelCapabilities(supports_tools=True, supports_json_mode=True, supports_vision=True, reasoning_optimized=True, context_tokens=1_048_576)),
    LadderRung(SONNET, ModelCapabilities(supports_tools=True, supports_json_mode=True, supports_vision=True, context_tokens=1_000_000)),
]

# OPUS_LADDER = reasoning/specialist tier: code + tool specialists, opus safety-net.
# (Cost-runaway history: ADR 0072 — keep claude-opus as the LAST rung, not first.)
OPUS_LADDER: list[LadderRung] = [
    LadderRung(LADDER_DEEPSEEK_V4_PRO, ModelCapabilities(**_REASON_BIG)),
    LadderRung(LADDER_GPT5_CODEX_MAX, ModelCapabilities(**dict(_REASON, context_tokens=400_000))),
    LadderRung(LADDER_GEMINI_31_CUSTOMTOOLS, ModelCapabilities(supports_tools=True, supports_json_mode=True, reasoning_optimized=True, context_tokens=1_048_576)),
    LadderRung(OPUS, ModelCapabilities(supports_tools=True, supports_json_mode=True, supports_vision=True, reasoning_optimized=True, context_tokens=200_000)),
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
        f"or pass a model alias like 'gpt-5.1-codex-max' / 'claude-opus-4-7'"
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
