"""Agent-to-Agent (A2A) integration via Xenocomm.

v1.5 is a config-only spike per [ADR 0004](../../docs/adr/0004-xenocomm-a2a.md):
operators add a ``xenocomm`` server to ``CHIMERA_MCP_SERVERS`` and the
existing MCP client (Phase 3.3) registers Xenocomm's tools under the
``mcp-xenocomm`` toolset.

This package adds the thin Python conveniences referenced by the ADR:

- :class:`AgentIdentity` — what this Chimera advertises to peers
- :func:`list_xenocomm_tools` — enumerate discovered Xenocomm tools
"""

from .identity import AgentIdentity
from .peers import list_xenocomm_tools

__all__ = ["AgentIdentity", "list_xenocomm_tools"]
