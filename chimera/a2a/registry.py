"""Filesystem-based peer registry.

Per ADR 0007 (v2.2). Each running Chimera writes a single JSON file under
``$CHIMERA_PEER_REGISTRY_DIR`` (default ``~/.chimera/peers/``) when its
MCP server starts, and removes it on graceful exit. Other Chimeras
enumerate the directory to discover peers.

A registry entry carries:

- ``agent_id`` — :class:`AgentIdentity.agent_id`
- ``version`` — Chimera version
- ``capabilities`` — what the peer advertises
- ``pid`` — process id (for stale-entry sweeps)
- ``host`` — hostname (lets a multi-host swarm decide reachability)
- ``reach`` — how a client should dial this peer; today only
  ``{"transport": "stdio", "command": [...], "env": {...}}``;
  v2.x will add ``{"transport": "http", "url": "..."}``
- ``registered_at`` — ISO timestamp
- ``schema_version`` — registry record schema version (currently 1)

The registry is intentionally a directory of small JSON files (not a
single rolling file) so concurrent writers don't collide and stale
entries can be removed by ``unlink``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .identity import AgentIdentity

REGISTRY_SCHEMA_VERSION = 1


def registry_dir() -> Path:
    """Resolve the peer registry directory, creating it if missing."""
    raw = os.environ.get("CHIMERA_PEER_REGISTRY_DIR")
    if raw:
        d = Path(raw).expanduser()
    else:
        d = Path.home() / ".chimera" / "peers"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class PeerEntry:
    agent_id: str
    version: str
    capabilities: tuple[str, ...]
    pid: int
    host: str
    reach: dict
    registered_at: str
    schema_version: int = REGISTRY_SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["capabilities"] = list(self.capabilities)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> PeerEntry:
        return cls(
            agent_id=str(data["agent_id"]),
            version=str(data.get("version", "?")),
            capabilities=tuple(data.get("capabilities") or ()),
            pid=int(data.get("pid", 0)),
            host=str(data.get("host", "")),
            reach=dict(data.get("reach") or {}),
            registered_at=str(data.get("registered_at", "")),
            schema_version=int(data.get("schema_version", REGISTRY_SCHEMA_VERSION)),
        )


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _safe_filename(agent_id: str) -> str:
    """Map an agent_id to a safe filename. Only [a-zA-Z0-9._-] allowed."""
    out = "".join(c if c.isalnum() or c in "._-" else "_" for c in agent_id)
    return f"{out}.json" if out else "anonymous.json"


def register(
    identity: AgentIdentity,
    *,
    reach: dict | None = None,
    dir: Path | None = None,
) -> Path:
    """Write a peer entry for this Chimera. Returns the entry path."""
    d = dir or registry_dir()
    host = socket.gethostname()
    entry = PeerEntry(
        agent_id=identity.agent_id,
        version=identity.version,
        capabilities=identity.capabilities,
        pid=os.getpid(),
        host=host,
        reach=reach or {"transport": "stdio", "command": ["chimera", "serve"]},
        registered_at=_utc_now_iso(),
    )
    path = d / _safe_filename(identity.agent_id)
    path.write_text(json.dumps(entry.to_dict(), indent=2, sort_keys=True))
    return path


def forget(agent_id: str, *, dir: Path | None = None) -> bool:
    """Remove an agent's registry entry. Returns True if a file was removed."""
    d = dir or registry_dir()
    path = d / _safe_filename(agent_id)
    if path.exists():
        path.unlink()
        return True
    return False


def list_peers(*, dir: Path | None = None) -> list[PeerEntry]:
    """Return all entries currently in the registry."""
    d = dir or registry_dir()
    out: list[PeerEntry] = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            out.append(PeerEntry.from_dict(data))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def sweep_stale(*, dir: Path | None = None) -> int:
    """Remove entries whose pid no longer exists. Returns count removed.

    Only removes entries whose ``host`` matches this host — we can't
    check liveness for remote peers from here.
    """
    d = dir or registry_dir()
    me = socket.gethostname()
    removed = 0
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("host") != me:
            continue
        pid = int(data.get("pid", 0))
        if pid <= 0:
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            p.unlink(missing_ok=True)
            removed += 1
        except PermissionError:
            # Process exists but is owned by someone else — treat as alive.
            continue
    return removed
