"""Sub-agent spawn tool — recursive ACT delegation.

Per ADR 0001 §"Concentric tool surface" (ring 4) + ADR 0003 deferred-items
§"Sub-agent capability inheritance".

A ``spawn_sub_agent`` tool call constructs a fresh :class:`ActExecutor`
with a chosen tier (defaulting to a sibling tier of the parent), runs a
single self-contained brief, and returns the sub-agent's final text.

Depth tracking uses ``contextvars`` so nested spawns from the same async
chain see a propagated counter. The default ``max_depth`` is 2 — enough
for "ask a specialist about X", not so much that a runaway spawn-storm
is possible.

The parent's tool policy is inherited unless the caller passes an
``allowed_tools`` allow-list, in which case only those tools are visible
to the sub-agent.
"""

from __future__ import annotations

import contextvars
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..providers import Provider
from ..providers.tiers import Provider as ProviderKind
from .dispatch import DispatchContext, Dispatcher
from .registry import ToolRegistry, default_registry

_sub_agent_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "chimera_sub_agent_depth", default=0
)


@dataclass
class SubAgentConfig:
    max_depth: int = 2
    default_tier: str = "haiku"
    max_rounds: int = 4


class SubAgentRunner:
    """Holds the deps a sub-agent ACT executor needs."""

    def __init__(
        self,
        *,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        registry: ToolRegistry,
        config: SubAgentConfig | None = None,
    ) -> None:
        self._providers = providers
        self._db = db
        self._registry = registry
        self._config = config or SubAgentConfig()

    async def run(
        self,
        brief: str,
        *,
        tier: str | None = None,
        allowed_tools: list[str] | None = None,
        cycle: int = -1,
    ) -> str:
        # Local import to avoid an import cycle with chimera.core.act.
        from ..core.act import ActExecutor

        executor = ActExecutor(
            dispatcher=Dispatcher(self._registry),
            providers=self._providers,
            db=self._db,
            tier=tier or self._config.default_tier,
            max_rounds=self._config.max_rounds,
        )
        context = DispatchContext(
            allow=frozenset(allowed_tools) if allowed_tools else frozenset(),
        )
        result = await executor.execute(brief, cycle=cycle, context=context)
        if result.final_text:
            return result.final_text
        return f"(sub-agent finished without text; finish_reason={result.finish_reason})"


SPAWN_SUB_AGENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "spawn_sub_agent",
        "description": (
            "IN-PROCESS sub-agent. Spawns a fresh ACT loop on a chosen model tier, "
            "INSIDE THIS Chimera. Use for: different-model second opinion, "
            "parallelisable subtask. Do NOT use when the user asks you to 'call a "
            "peer' or 'talk to another Chimera' — that's a different MCP tool "
            "(mcp-<peer>-*). Briefs MUST be self-contained; the sub-agent has no "
            "memory of the parent context — paste any required inputs verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": "Self-contained task description for the sub-agent.",
                },
                "tier": {
                    "type": "string",
                    "enum": ["haiku", "sonnet", "opus"],
                    "description": "Tier to run on (default haiku).",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional allow-list of tool names the sub-agent may call. "
                        "Empty/omitted = inherit parent's tool surface."
                    ),
                },
            },
            "required": ["brief"],
        },
    },
}


def _make_handler(runner: SubAgentRunner):
    async def _handler(args: dict[str, Any], context: DispatchContext) -> str:
        depth = _sub_agent_depth.get()
        if depth >= runner._config.max_depth:  # noqa: SLF001 — friendly access
            return (
                f"[sub-agent depth limit reached ({runner._config.max_depth}); "
                "refusing to spawn deeper]"
            )
        brief = args.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            raise ValueError("brief must be a non-empty string")
        tier = args.get("tier") or runner._config.default_tier  # noqa: SLF001
        allowed = args.get("allowed_tools")
        if allowed is not None and not isinstance(allowed, list):
            raise ValueError("allowed_tools must be a list of strings")

        token = _sub_agent_depth.set(depth + 1)
        try:
            return await runner.run(
                brief, tier=tier, allowed_tools=allowed, cycle=-1
            )
        finally:
            _sub_agent_depth.reset(token)

    return _handler


def register_sub_agent_tool(
    runner: SubAgentRunner,
    registry: ToolRegistry | None = None,
) -> None:
    reg = registry or default_registry()
    reg.register(
        name="spawn_sub_agent",
        toolset="core",
        schema=SPAWN_SUB_AGENT_SCHEMA,
        handler=_make_handler(runner),
        description="Delegate a focused brief to a specialist sub-agent.",
        override=True,
    )
