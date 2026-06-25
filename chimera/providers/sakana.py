"""Sakana Fugu provider — OpenAI-compatible multi-agent model.

Sakana Fugu (https://sakana.ai/fugu/) is a multi-agent orchestration system
exposed as a single OpenAI-compatible model API. Two models — ``fugu`` (balanced)
and ``fugu-ultra`` (coordinates expert agents for hard multi-step reasoning).
It speaks the same ``/chat/completions`` surface as OpenRouter, so the whole
adapter is inherited from :class:`OpenAICompatibleProvider`.

Auth: ``SAKANA_API_KEY`` (``FUGU_API_KEY`` accepted as a fallback). The endpoint
defaults to ``https://api.sakana.ai/v1/chat/completions`` and can be overridden
with ``SAKANA_BASE_URL`` / ``FUGU_BASE_URL`` (the API root, a ``…/v1`` root, or a
full chat/completions URL — all normalised).

Note: Fugu IGNORES ``temperature`` / ``top_p`` / ``seed`` (its diversity is
internal to the ensemble), so sampling-based variation must come from re-calling.
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatibleProvider

_DEFAULT_URL = "https://api.sakana.ai/v1/chat/completions"


def _normalize_base_url(base: str) -> str:
    """Accept an API root, a ``…/v1`` root, or a full chat/completions URL."""
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


class SakanaProvider(OpenAICompatibleProvider):
    name = "sakana"
    default_url = _DEFAULT_URL
    api_key_env = "SAKANA_API_KEY"

    def __init__(self, api_key: str | None = None, *, timeout: float = 60.0) -> None:
        key = (
            api_key
            or os.environ.get("SAKANA_API_KEY")
            or os.environ.get("FUGU_API_KEY")
        )
        if not key:
            raise RuntimeError("SAKANA_API_KEY (or FUGU_API_KEY) not set")
        override = os.environ.get("SAKANA_BASE_URL") or os.environ.get("FUGU_BASE_URL")
        base_url = _normalize_base_url(override) if override else None
        super().__init__(key, base_url=base_url, timeout=timeout)
