"""Provider abstraction package."""

from .anthropic import AnthropicProvider
from .base import ChatChunk, ChatMessage, Provider
from .messages import (
    ChatResponse,
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .openai_compat import OpenAICompatibleProvider
from .openrouter import OpenRouterProvider
from .sakana import SakanaProvider
from .tiers import (
    HAIKU,
    HAIKU_LADDER,
    CODE_LADDER,
    MODEL_TIERS,
    OPUS,
    OPUS_LADDER,
    SONNET,
    SONNET_LADDER,
    TIER_LADDERS,
    LadderRung,
    ModelCapabilities,
    ModelConfig,
)
from .tiers import Provider as ProviderKind
from .tiers import eligible_rungs, resolve_rung, select_rung


def get_provider(name: str) -> Provider:
    """Return a fresh provider instance by name (raises on unknown / missing key).

    The single seam for selecting a chat provider from a string (CLI flags,
    config). Each provider reads its own API key from the environment.
    """
    key = name.strip().lower()
    if key == "anthropic":
        return AnthropicProvider()
    if key == "openrouter":
        return OpenRouterProvider()
    if key == "sakana":
        return SakanaProvider()
    raise ValueError(f"unknown provider: {name!r} (expected anthropic/openrouter/sakana)")


__all__ = [
    "AnthropicProvider",
    "OpenAICompatibleProvider",
    "SakanaProvider",
    "get_provider",
    "ChatChunk",
    "ChatMessage",
    "ChatResponse",
    "ContentBlock",
    "Message",
    "OpenRouterProvider",
    "Provider",
    "TextBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "ProviderKind",
    "ModelConfig",
    "ModelCapabilities",
    "LadderRung",
    "MODEL_TIERS",
    "TIER_LADDERS",
    "CODE_LADDER",
    "HAIKU",
    "SONNET",
    "OPUS",
    "HAIKU_LADDER",
    "SONNET_LADDER",
    "OPUS_LADDER",
    "eligible_rungs",
    "resolve_rung",
    "select_rung",
]
