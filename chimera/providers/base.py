"""Provider abstraction — streaming chat + tool-using chat.

Per ADR 0001 §"LLM provider abstraction": custom thin adapters wrapping
the official `anthropic` SDK and raw `httpx` for OpenRouter. Two narrow
adapters beat a third-party wrapper.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from .messages import ChatResponse, Message


@dataclass
class ChatMessage:
    """Simple text-only message — used by :meth:`Provider.stream`."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatChunk:
    """One streaming delta from a provider."""

    text: str
    finish_reason: str | None = None  # "stop" | "length" | "tool_use" | None


class Provider(ABC):
    """Streaming chat + non-streaming tool-using chat."""

    name: str

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model_id: str,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Yield ChatChunks as the model produces text."""
        ...

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:
        """Non-streaming single-turn completion.

        Returns a :class:`ChatResponse` with text + tool_uses + a normalised
        stop_reason. Caller drives the multi-turn loop in
        :mod:`chimera.core.act`.
        """
        ...
