"""The always-exposed ``chimera-identity`` tool — peer handshake target.

Per ADR 0006 (v2.1): every Chimera server unconditionally advertises a
single tool, ``chimera-identity``, that returns its
:class:`~chimera.a2a.identity.AgentIdentity` payload as a JSON string.
A peer's first move on connecting MUST be to call this tool — it's how
two Chimeras find out *who* they're talking to before deciding *what*
to allow each other to do.

The identity tool is intentionally:

- **Allow-list-bypass**: it ignores ``CHIMERA_PEER_EXPOSED_TOOLS``.
- **Side-effect-free**: pure read of in-memory state; no DB writes.
- **Cheap**: no LLM call, no network, no subprocess.
- **Stable name**: peers can hardcode ``chimera-identity``.
"""

from __future__ import annotations

import json
from typing import Any

from ..a2a.identity import AgentIdentity
from ..tools import DispatchContext, ToolRegistry


IDENTITY_TOOL_NAME = "chimera-identity"


IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": IDENTITY_TOOL_NAME,
        "description": (
            "Return this Chimera's identity payload (agent_id, version, role, "
            "capabilities) as a JSON string. Always available; ignores the "
            "CHIMERA_PEER_EXPOSED_TOOLS allow-list."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def make_identity_handler():
    """Return an async handler closing over a freshly-built AgentIdentity."""
    identity = AgentIdentity()

    async def _handler(args: dict, context: DispatchContext) -> str:
        return json.dumps(identity.to_dict(), sort_keys=True)

    return _handler


def register_identity_tool(registry: ToolRegistry) -> None:
    """Idempotent: register the identity tool against the registry."""
    registry.register(
        name=IDENTITY_TOOL_NAME,
        toolset="peer",
        schema=IDENTITY_SCHEMA,
        handler=make_identity_handler(),
        description="Peer identity handshake (always exposed).",
        override=True,
    )
