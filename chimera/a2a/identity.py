"""Agent identity — what this Chimera tells peers about itself."""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import asdict, dataclass, field

from .. import __version__


def _default_agent_id() -> str:
    """Stable-ish agent id: env override, else host-derived deterministic, else uuid4."""
    env_id = os.environ.get("CHIMERA_AGENT_ID")
    if env_id:
        return env_id
    try:
        host = socket.gethostname()
    except OSError:
        host = "unknown"
    return f"chimera-{host}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class AgentIdentity:
    """The handshake payload Chimera offers an A2A peer."""

    agent_id: str = field(default_factory=_default_agent_id)
    version: str = __version__
    role: str = "chimera"
    capabilities: tuple[str, ...] = (
        "shell",
        "http_fetch",
        "web_search",
        "code_exec",
        "spawn_sub_agent",
    )

    def to_dict(self) -> dict:
        return asdict(self)
