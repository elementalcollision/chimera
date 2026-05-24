"""Chimera's MCP server surface — peers call us via this.

Per ADR 0005 (v2.0): Chimera flips from MCP-client-only (v1) to also
being an MCP server. A peer Chimera (or any MCP-compatible client) can
register us in their ``CHIMERA_MCP_SERVERS`` env and call our exposed
tools.

Safety posture (v2.0):

- **Default deny.** No tool is exposed to peers unless explicitly
  listed in ``CHIMERA_PEER_EXPOSED_TOOLS`` (comma-separated names).
- **Per-call dispatch context** carries ``peer_call=True`` so future
  policy layers can gate writes / sensitive tools differently for
  peer-originated calls than for in-process ACT calls.
- **Stdio transport.** The peer launches us as a subprocess. HTTP /
  SSE transports are deferred to v2.1 once auth / TLS questions land.

The server reuses Chimera's existing tool registry and dispatcher —
all policy pipeline layers (global deny, per-context deny/allow,
availability, requires_env) apply transparently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ..tools import (
    DispatchContext,
    Dispatcher,
    ToolRegistry,
    default_registry,
    register_core_tools,
)
from .dialectic_tool import ASK_TOOL_NAME, register_ask_tool
from .identity_tool import IDENTITY_TOOL_NAME, register_identity_tool
from .kfm_tool import KFM_STATE_TOOL_NAME, register_kfm_state_tool

logger = logging.getLogger(__name__)


_ENV_EXPOSED = "CHIMERA_PEER_EXPOSED_TOOLS"


def exposed_tool_names(env_value: str | None = None) -> set[str]:
    """Parse the allow-list from env (or arg). Empty → default-deny."""
    raw = env_value if env_value is not None else os.environ.get(_ENV_EXPOSED, "")
    return {t.strip() for t in raw.split(",") if t.strip()}


@dataclass
class ChimeraMCPServer:
    """Wraps an :class:`mcp.server.Server` around Chimera's dispatcher."""

    name: str
    registry: ToolRegistry
    dispatcher: Dispatcher
    exposed: frozenset[str]
    server: Server

    @classmethod
    def from_env(
        cls,
        *,
        name: str = "chimera",
        registry: ToolRegistry | None = None,
        exposed: set[str] | None = None,
    ) -> ChimeraMCPServer:
        reg = registry or default_registry()
        # Built-in tools + always-exposed peer surface (identity, KFM state).
        register_core_tools(reg)
        register_identity_tool(reg)
        register_kfm_state_tool(reg)
        register_ask_tool(reg)
        dispatcher = Dispatcher(reg)
        operator_allow = set(exposed if exposed is not None else exposed_tool_names())
        # Always advertised — peers depend on these for handshake + swarm view.
        operator_allow.add(IDENTITY_TOOL_NAME)
        operator_allow.add(KFM_STATE_TOOL_NAME)
        operator_allow.add(ASK_TOOL_NAME)
        allowed = frozenset(operator_allow)
        srv = build_server(name=name, registry=reg, dispatcher=dispatcher, exposed=allowed)
        return cls(
            name=name, registry=reg, dispatcher=dispatcher, exposed=allowed, server=srv
        )


def _openai_to_mcp_tool(schema: dict[str, Any]) -> mt.Tool:
    fn = schema.get("function") if schema.get("type") == "function" else schema
    return mt.Tool(
        name=fn["name"],
        description=fn.get("description", ""),
        inputSchema=fn.get("parameters", {"type": "object", "properties": {}}),
    )


def build_server(
    *,
    name: str,
    registry: ToolRegistry,
    dispatcher: Dispatcher,
    exposed: frozenset[str],
) -> Server:
    """Construct the low-level MCP Server with list_tools + call_tool wired."""
    server: Server = Server(name=name, instructions="Chimera peer-callable surface")

    @server.list_tools()
    async def _list_tools() -> list[mt.Tool]:
        out: list[mt.Tool] = []
        for tool_name in registry.names():
            if tool_name not in exposed:
                continue
            entry = registry.get(tool_name)
            if entry is None:
                continue
            out.append(_openai_to_mcp_tool(entry.schema))
        logger.debug("MCP list_tools: returning %d tool(s)", len(out))
        return out

    @server.call_tool()
    async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> list[mt.TextContent]:
        if tool_name not in exposed:
            return [
                mt.TextContent(
                    type="text",
                    text=f"tool {tool_name!r} is not exposed to peers",
                )
            ]
        # v2.7: build the dispatch context from the attested peer (if any).
        from ..a2a import PeerTrustPolicy, PolicyDecision
        from .peer_auth import current_peer, lookup_peer_state

        peer_name = current_peer.get()
        trust_tier = "T1"  # v2.0 baseline for unidentified / anonymous peers
        session_id = "peer"
        if peer_name is not None:
            session_id = f"peer:{peer_name}"
            peer_state = lookup_peer_state(peer_name)
            decision = PeerTrustPolicy().evaluate(peer_state)
            if decision.decision is PolicyDecision.REFUSE:
                return [
                    mt.TextContent(
                        type="text",
                        text=f"refused: peer {peer_name!r}: {decision.reason}",
                    )
                ]
            if decision.decision is PolicyDecision.ALLOW:
                trust_tier = "T2"
            # DEGRADE / fallthrough → keep T1.
        ctx = DispatchContext(trust_tier=trust_tier, session_id=session_id)
        try:
            result = await dispatcher.dispatch(tool_name, arguments or {}, ctx)
        except Exception as exc:
            logger.exception("MCP call_tool %s failed", tool_name)
            return [mt.TextContent(type="text", text=f"error: {exc}")]
        return [mt.TextContent(type="text", text=result)]

    return server


async def serve_stdio(name: str = "chimera") -> int:
    """Run the MCP server on stdio until peer disconnects.

    On start, register this Chimera in the peer registry (per ADR 0007);
    on exit (graceful or otherwise), remove the entry.
    """
    from ..a2a import AgentIdentity
    from ..a2a import forget as _forget_peer
    from ..a2a import register as _register_peer
    from ..core import assert_no_errors

    assert_no_errors()
    cms = ChimeraMCPServer.from_env(name=name)
    if not cms.exposed:
        logger.warning(
            "no tools exposed to peers; set %s to a comma-separated allow-list",
            _ENV_EXPOSED,
        )
    identity = AgentIdentity()
    registry_path = None
    try:
        registry_path = _register_peer(identity)
        logger.info("registered in peer registry: %s", registry_path)
    except OSError:
        logger.exception("peer registry write failed; continuing without it")

    init_opts = cms.server.create_initialization_options()
    try:
        async with stdio_server() as (read, write):
            await cms.server.run(read, write, init_opts)
    finally:
        try:
            _forget_peer(identity.agent_id)
        except OSError:
            pass
    return 0
