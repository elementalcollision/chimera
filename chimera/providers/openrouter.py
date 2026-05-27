"""OpenRouter provider — OpenAI-shaped Chat Completions over httpx.

OpenRouter exposes an OpenAI-compatible API at ``/api/v1/chat/completions``.
We hit it directly with httpx rather than depending on the openai SDK,
keeping the dependency surface small.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ChatChunk, ChatMessage, Provider
from .messages import (
    ChatResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


_STOP_REASON_MAP = {
    "stop": "stop",
    "end_turn": "stop",
    "tool_calls": "tool_use",
    "length": "length",
    "content_filter": "stop",
}


def _serialize_messages_openai(
    messages: list[Message], system: str | None = None
) -> list[dict[str, Any]]:
    """Convert internal Messages → OpenAI/OpenRouter API messages.

    OpenAI splits tool_use (on assistant) from tool_result (its own ``role="tool"``
    message). We unpack our Message blocks accordingly.
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "system":
            out.append({"role": "system", "content": m.text()})
            continue
        if m.role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in m.blocks:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input),
                            },
                        }
                    )
            msg: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
            continue
        # role == "user": text + tool_result blocks need different unpacking.
        # OpenAI: tool_result becomes a separate role="tool" message.
        text_parts = []
        for block in m.blocks:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolResultBlock):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": block.content,
                    }
                )
        if text_parts:
            out.append({"role": "user", "content": "".join(text_parts)})
    return out

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        referer: str | None = None,
        title: str | None = "chimera",
        timeout: float = 60.0,
    ) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        # OpenRouter likes (but does not require) HTTP-Referer + X-Title.
        if referer:
            self._headers["HTTP-Referer"] = referer
        if title:
            self._headers["X-Title"] = title
        self._timeout = timeout
        # Long-lived AsyncClient — created lazily on the loop that
        # first invokes us, then reused for every subsequent call.
        # Rationale: with per-call ``async with httpx.AsyncClient`` the
        # context manager teardown accumulates anyio-backend state on
        # Python 3.14. Even when the calling event loop is the
        # persistent loop (PRs #93/#94), enough repeated teardown
        # cycles wedge the executor and lock the next-future-result
        # mutex chain — the F2 LoCoMo full-corpus sweep reproduces at
        # the conv-26 → conv-30 boundary (~5th conversation, hundreds
        # of completed calls), with the canonical 3-thread idle stack
        # signature. One client per provider instance keeps connection
        # pool + transport lifetime bound to the process, which is
        # what the textbook httpx async pattern recommends anyway.
        # See mind/research/f2-cross-conv-deadlock-2026-05-27.md.
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a long-lived AsyncClient bound to the current loop.

        If the current running loop is different from the one that
        owns the cached client (rare — happens in tests that build
        providers ad-hoc on different loops), drop the old client and
        create a new one. The closed httpx client is GC'd; the
        replacement lives on the new loop. Never called outside a
        coroutine, so ``asyncio.get_running_loop`` is always defined.
        """
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:  # noqa: BLE001 — best-effort close
                    pass
            self._client = httpx.AsyncClient(
                timeout=self._timeout, headers=self._headers,
            )
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        """Close the underlying AsyncClient, if any. Idempotent."""
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None
                self._client_loop = None

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model_id: str,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for m in messages:
            oai_messages.append({"role": m.role, "content": m.content})

        body = {
            "model": model_id,
            "messages": oai_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        client = await self._get_client()
        async with client.stream(
            "POST", _OPENROUTER_URL, json=body
        ) as resp:
            if resp.status_code >= 400:
                body_bytes = await resp.aread()
                snippet = body_bytes.decode(errors="replace")[:500]
                raise httpx.HTTPStatusError(
                    f"OpenRouter {resp.status_code}: {snippet}",
                    request=resp.request,
                    response=resp,
                )
            async for raw_line in resp.aiter_lines():
                if not raw_line or not raw_line.startswith("data: "):
                    continue
                payload = raw_line[len("data: "):]
                if payload.strip() == "[DONE]":
                    yield ChatChunk(text="", finish_reason="stop")
                    return
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                finish = choice.get("finish_reason")
                if text:
                    yield ChatChunk(text=text)
                if finish:
                    yield ChatChunk(text="", finish_reason=finish)
                    return

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
        temperature: float | None = None,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": _serialize_messages_openai(messages, system=system),
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature

        from .retry import retry_call

        async def _once() -> dict[str, Any]:
            client = await self._get_client()
            resp = await client.post(_OPENROUTER_URL, json=body)
            if resp.status_code >= 400:
                snippet = resp.text[:500]
                raise httpx.HTTPStatusError(
                    f"OpenRouter {resp.status_code}: {snippet}",
                    request=resp.request,
                    response=resp,
                )
            return resp.json()

        t0 = time.monotonic()
        payload = await retry_call(_once)
        latency_ms = int((time.monotonic() - t0) * 1000)

        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        finish_raw = choice.get("finish_reason") or "stop"

        tool_uses: list[ToolUseBlock] = []
        for tc in message.get("tool_calls") or []:
            tc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                # Match Reggio's normalize_tool_input shape so the ACT guard
                # can unwrap downstream.
                args = {"_raw": args_raw}
            tool_uses.append(ToolUseBlock(id=tc_id, name=fn.get("name", ""), input=args))

        stop_reason = _STOP_REASON_MAP.get(finish_raw, finish_raw)
        usage = payload.get("usage") or {}
        return ChatResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            model_id=model_id,
            provider=self.name,
            latency_ms=latency_ms,
        )
