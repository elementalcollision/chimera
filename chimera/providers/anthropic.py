"""Anthropic provider — wraps the official anthropic SDK."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from .base import ChatChunk, ChatMessage, Provider
from .messages import (
    ChatResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


# Stop-reason normalisation per ADR 0001 (consumer-facing strings).
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_use",
}


def _serialize_message_anthropic(m: Message) -> dict[str, Any]:
    """Convert internal Message → Anthropic API message dict."""
    content: list[dict[str, Any]] = []
    for block in m.blocks:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            content.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        elif isinstance(block, ToolResultBlock):
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
            )
    return {"role": m.role, "content": content}


def _openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI ``{type: function, function: {...}}`` schemas to
    Anthropic ``{name, description, input_schema}`` form."""
    out: list[dict[str, Any]] = []
    for t in tools:
        fn = t.get("function") if t.get("type") == "function" else t
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=key)

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model_id: str,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        anth_messages = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        # Anthropic API: system is a top-level kwarg, not a role entry.
        if system is None:
            system_msgs = [m.content for m in messages if m.role == "system"]
            system = "\n\n".join(system_msgs) if system_msgs else None

        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": anth_messages,
        }
        if system:
            kwargs["system"] = system

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # Text deltas
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield ChatChunk(text=event.delta.text)
            final = await stream.get_final_message()
            yield ChatChunk(text="", finish_reason=final.stop_reason or "stop")

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:
        system_parts: list[str] = []
        wire_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.text())
            else:
                wire_messages.append(_serialize_message_anthropic(m))
        if system is not None:
            system_parts.insert(0, system)
        kwargs: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": wire_messages,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(s for s in system_parts if s)
        if tools:
            kwargs["tools"] = _openai_tools_to_anthropic(tools)

        t0 = time.monotonic()
        resp = await self._client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - t0) * 1000)

        text_parts: list[str] = []
        tool_uses: list[ToolUseBlock] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(
                    ToolUseBlock(id=block.id, name=block.name, input=dict(block.input))
                )
        stop_reason = _STOP_REASON_MAP.get(resp.stop_reason or "stop", "stop")
        return ChatResponse(
            text="".join(text_parts),
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            input_tokens=getattr(resp.usage, "input_tokens", None),
            output_tokens=getattr(resp.usage, "output_tokens", None),
            model_id=model_id,
            provider=self.name,
            latency_ms=latency_ms,
        )
