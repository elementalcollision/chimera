"""The always-exposed ``chimera-ask`` MCP tool (ADR 0133).

Phase 3 #2 of the Honcho-inspired roadmap. Federated peers (or any
MCP-aware caller) can ask Chimera natural-language questions about
the peers it knows — including itself.

This tool is **deterministic-only**: it gathers context from disk
(peer cards, peer-trust journal, peer-beliefs JSONL) and returns the
**rendered prompt** rather than an LLM-generated answer. The peer
makes its own LLM call against that prompt with its own provider
budget. This keeps the federation surface free of model-selection
concerns and avoids one Chimera burning another Chimera's cost cap
on an unbounded inbound query.

Operators who want an LLM-generated answer use the CLI verb
``chimera peers ask``, which calls the local provider stack against
the same prompt.
"""

from __future__ import annotations

import json
from typing import Any

from ..tools import DispatchContext, ToolRegistry


ASK_TOOL_NAME = "chimera-ask"

ASK_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ASK_TOOL_NAME,
        "description": (
            "Return a prompt grounded in what this Chimera knows about a peer "
            "(peer card, recent trust decisions, observer/observed beliefs). "
            "The caller runs the LLM with their own provider budget; this "
            "tool does no model calls. Always available; ignores the "
            "CHIMERA_PEER_EXPOSED_TOOLS allow-list. Pure read; no side-effects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "peer_name": {
                    "type": "string",
                    "description": (
                        "Name of the peer to query against. Use 'self' for "
                        "Chimera's own state (matches the self-card)."
                    ),
                },
                "question": {
                    "type": "string",
                    "description": "Natural-language question about the peer.",
                },
            },
            "required": ["peer_name", "question"],
        },
    },
}


async def _handler(args: dict, context: DispatchContext) -> str:
    from pathlib import Path

    from ..a2a.dialectic import build_dialectic_prompt, gather_dialectic_context
    from ..core import LoopConfig

    peer_name = str(args.get("peer_name", "")).strip()
    question = str(args.get("question", "")).strip()
    if not peer_name or not question:
        return json.dumps({
            "error": "peer_name and question are required",
        })
    cfg = LoopConfig.from_env()
    ctx = gather_dialectic_context(peer_name, mind_dir=Path(cfg.mind_dir))
    prompt = build_dialectic_prompt(ctx, question)
    return json.dumps({
        "peer_name": peer_name,
        "question": question,
        "prompt": prompt,
        "sources_used": ctx.sources_used,
        "is_empty_context": ctx.is_empty(),
    })


def register_ask_tool(registry: ToolRegistry) -> None:
    """Idempotent: register the dialectic ``chimera-ask`` tool."""
    registry.register(
        name=ASK_TOOL_NAME,
        toolset="peer",
        schema=ASK_SCHEMA,
        handler=_handler,
        description="Peer dialectic prompt assembly (always exposed).",
        override=True,
    )
