"""Agent-to-Agent (A2A) — identity, peer discovery, handshake.

v1.5 was a Xenocomm-MCP-client spike. v2.1 adds the identity handshake
that lets two Chimeras attest to each other before any policy-gated
work happens.

- :class:`AgentIdentity` — what this Chimera advertises to peers
- :func:`list_xenocomm_tools` — Xenocomm tools discovered via MCP
- :func:`list_peer_chimeras` — server names of peer Chimeras discovered
- :func:`fetch_peer_identity` — call a peer's ``chimera-identity`` tool
"""

from .identity import AgentIdentity
from .peers import (
    fetch_peer_identity,
    fetch_peer_kfm,
    list_peer_chimeras,
    list_xenocomm_tools,
)
from .trust_policy import (
    PeerStateCache,
    PeerTrustPolicy,
    PolicyDecision,
    PolicyResult,
    is_always_allowed_peer_tool,
    peer_name_from_tool,
)
from .registry import (
    PeerEntry,
    forget,
    list_peers,
    register,
    registry_dir,
    sweep_stale,
)

__all__ = [
    "AgentIdentity",
    "PeerEntry",
    "fetch_peer_identity",
    "fetch_peer_kfm",
    "forget",
    "list_peer_chimeras",
    "list_peers",
    "list_xenocomm_tools",
    "PeerStateCache",
    "PeerTrustPolicy",
    "PolicyDecision",
    "PolicyResult",
    "is_always_allowed_peer_tool",
    "peer_name_from_tool",
    "register",
    "registry_dir",
    "sweep_stale",
]
