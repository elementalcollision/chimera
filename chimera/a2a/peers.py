"""Peer-discovery helpers.

v1.5 surfaced Xenocomm tool enumeration; v2.1 adds the identity handshake.
"""

from __future__ import annotations

import json
from typing import Any

from ..tools import DispatchContext, Dispatcher, ToolRegistry, default_registry


def list_xenocomm_tools(registry: ToolRegistry | None = None) -> list[str]:
    """Return the names of registered tools whose toolset is ``mcp-xenocomm``."""
    reg = registry or default_registry()
    return sorted(
        name for name in reg.names()
        if (entry := reg.get(name)) is not None and entry.toolset == "mcp-xenocomm"
    )


def list_peer_chimeras(registry: ToolRegistry | None = None) -> list[str]:
    """Return server-prefix names for every registered peer Chimera.

    Looks for tools named ``mcp-<server>-chimera-identity`` and extracts
    ``<server>`` so the caller can call them by name.
    """
    reg = registry or default_registry()
    out: list[str] = []
    for name in reg.names():
        if not name.endswith("-chimera-identity"):
            continue
        if name.startswith("mcp-"):
            mid = name[len("mcp-"):-len("-chimera-identity")]
            out.append(mid)
    return sorted(out)


async def fetch_peer_identity(
    peer_name: str,
    *,
    registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Call ``mcp-<peer_name>-chimera-identity`` and parse the JSON response."""
    reg = registry or default_registry()
    tool_name = f"mcp-{peer_name}-chimera-identity"
    if reg.get(tool_name) is None:
        raise LookupError(
            f"no identity tool for peer {peer_name!r} "
            f"(expected registered tool {tool_name!r})"
        )
    dispatcher = Dispatcher(reg)
    raw = await dispatcher.dispatch(tool_name, {}, DispatchContext())
    return json.loads(raw)
