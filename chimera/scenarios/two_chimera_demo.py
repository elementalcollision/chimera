"""v2.0 demo — two Chimeras talking via MCP.

Chimera-B (this process) launches Chimera-A as a subprocess via
``chimera serve``, with shell exposed under
``CHIMERA_PEER_EXPOSED_TOOLS`` and its own isolated mind/state dirs.
The MCP client registers A's tools under ``mcp-chimera-a-*`` and
dispatches one call. We verify the returned text contains a marker
file that A's filesystem has and B's filesystem doesn't.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from ..tools import (
    DispatchContext,
    Dispatcher,
    MCPServerConfig,
    ToolRegistry,
    register_mcp_servers,
)


@dataclass
class TwoChimeraResult:
    discovered_tools: list[str]
    peer_identity: dict | None
    call_result: str
    ok: bool


async def _arun(
    peer_root: Path,
    *,
    marker_name: str = "two_chimera_marker.txt",
) -> TwoChimeraResult:
    peer_mind = peer_root / "mind"
    peer_state = peer_root / "state"
    peer_mind.mkdir(parents=True, exist_ok=True)
    peer_state.mkdir(parents=True, exist_ok=True)
    (peer_mind / marker_name).write_text("hello from peer Chimera-A\n", encoding="utf-8")

    cfg = {
        "chimera-a": MCPServerConfig(
            name="chimera-a",
            command="uv",
            args=("run", "chimera", "serve"),
            env={
                "CHIMERA_PEER_EXPOSED_TOOLS": "shell",
                "CHIMERA_MIND_DIR": str(peer_mind),
                "CHIMERA_STATE_DIR": str(peer_state),
                # Preserve PATH so `uv` is locatable in the subprocess env.
                "PATH": os.environ.get("PATH", ""),
            },
        )
    }
    reg = ToolRegistry()
    await register_mcp_servers(cfg, reg)
    discovered = sorted(reg.names())

    # v2.1: handshake first.
    from ..a2a import fetch_peer_identity

    peer_identity = await fetch_peer_identity("chimera-a", registry=reg)

    dispatcher = Dispatcher(reg)
    output = await dispatcher.dispatch(
        "mcp-chimera-a-shell",
        {"argv": ["ls", "."]},
        DispatchContext(),
    )
    ok = (
        marker_name in output
        and "[exit=0]" in output
        and peer_identity.get("role") == "chimera"
        and bool(peer_identity.get("agent_id"))
    )
    return TwoChimeraResult(
        discovered_tools=discovered,
        peer_identity=peer_identity,
        call_result=output,
        ok=ok,
    )


def run_two_chimera_demo(peer_root: Path) -> TwoChimeraResult:
    return asyncio.run(_arun(peer_root))
