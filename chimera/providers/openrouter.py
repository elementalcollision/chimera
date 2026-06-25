"""OpenRouter provider — OpenAI-shaped Chat Completions over httpx.

OpenRouter exposes an OpenAI-compatible API at ``/api/v1/chat/completions``.
The whole adapter lives in :class:`OpenAICompatibleProvider`; this module is the
thin OpenRouter specialisation (endpoint + key env + the optional HTTP-Referer /
X-Title headers OpenRouter likes). We hit it directly with httpx rather than the
openai SDK, keeping the dependency surface small.
"""

from __future__ import annotations

# Re-exported for back-compat: callers/tests have imported these from here.
from .openai_compat import (  # noqa: F401
    _STOP_REASON_MAP,
    OpenAICompatibleProvider,
    _serialize_messages_openai,
)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    default_url = _OPENROUTER_URL
    api_key_env = "OPENROUTER_API_KEY"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        referer: str | None = None,
        title: str | None = "chimera",
        timeout: float = 60.0,
    ) -> None:
        # OpenRouter likes (but does not require) HTTP-Referer + X-Title.
        extra: dict[str, str] = {}
        if referer:
            extra["HTTP-Referer"] = referer
        if title:
            extra["X-Title"] = title
        # Base resolves the key from OPENROUTER_API_KEY when api_key is None.
        super().__init__(api_key, extra_headers=extra or None, timeout=timeout)
