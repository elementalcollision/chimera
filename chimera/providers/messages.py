"""Rich message model for tool-using conversations.

Both Anthropic and OpenRouter (OpenAI-shape) support multi-turn tool use,
but their wire formats differ:

- Anthropic: messages have ``content`` as a list of typed blocks
  (``text``, ``tool_use``, ``tool_result``); ``system`` is a top-level kwarg.
- OpenAI/OpenRouter: messages have a flat ``content`` string + ``tool_calls``
  on assistant turns; tool results are a separate ``role="tool"`` message
  with ``tool_call_id``; ``system`` is a regular message.

We model both as a normalised internal :class:`Message` carrying typed
:class:`ContentBlock` items, and each provider serialises down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    blocks: list[ContentBlock] = field(default_factory=list)

    # ── convenience constructors ────────────────────────

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role="system", blocks=[TextBlock(text=text)])

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", blocks=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str, tool_uses: list[ToolUseBlock] | None = None) -> Message:
        blocks: list[ContentBlock] = []
        if text:
            blocks.append(TextBlock(text=text))
        if tool_uses:
            blocks.extend(tool_uses)
        return cls(role="assistant", blocks=blocks)

    @classmethod
    def tool_results(cls, results: list[ToolResultBlock]) -> Message:
        """Tool results are delivered as the next user turn in Anthropic's API."""
        return cls(role="user", blocks=list(results))

    # ── helpers ─────────────────────────────────────────

    def text(self) -> str:
        return "".join(b.text for b in self.blocks if isinstance(b, TextBlock))


@dataclass
class ChatResponse:
    """One non-streaming turn from a provider."""

    text: str                              # concatenated assistant text
    tool_uses: list[ToolUseBlock]
    stop_reason: str                       # "stop" | "tool_use" | "length" | "error"
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_id: str = ""
    provider: str = ""
    latency_ms: int = 0
    # Reasoning models surface their deliberation here (OpenRouter `message.reasoning`)
    # SEPARATELY from `text`; when budget is reasoning-heavy `text` can be empty while
    # this is populated. Callers that just want the answer ignore it; the guardrail
    # eval falls back to it so a reasoning model yields a real verdict (ADR 0186 B.4j).
    reasoning: str = ""
