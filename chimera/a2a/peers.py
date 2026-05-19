"""Peer-discovery helpers.

v1.5 is intentionally thin: peer-discovery means "which Xenocomm tools
has the MCP loader registered against my dispatcher?" Anything richer
(gossip, registry, identity handshake) is v2.
"""

from __future__ import annotations

from ..tools import ToolRegistry, default_registry


def list_xenocomm_tools(registry: ToolRegistry | None = None) -> list[str]:
    """Return the names of registered tools whose toolset is ``mcp-xenocomm``."""
    reg = registry or default_registry()
    return sorted(
        name for name in reg.names()
        if (entry := reg.get(name)) is not None and entry.toolset == "mcp-xenocomm"
    )
