# ADR 0007 — Peer registry (v2.2)

**Status:** Accepted. Anchors v2.2. Builds on
[ADR 0006](0006-identity-handshake.md) and feeds the v2.3 swarm-KFM
work.

## Context

In v2.1, two Chimeras can find each other only via hand-edited
``CHIMERA_MCP_SERVERS`` entries. That doesn't scale to a swarm — there
needs to be a place where running Chimeras *announce themselves* and
other Chimeras can read.

## Decision: a directory of JSON files

Each running Chimera writes a single file when its MCP server starts,
and removes it on graceful exit:

```
$CHIMERA_PEER_REGISTRY_DIR/<agent_id>.json
```

Default ``CHIMERA_PEER_REGISTRY_DIR`` is ``~/.chimera/peers/``. Each file
contains a :class:`PeerEntry` JSON object:

```json
{
  "schema_version": 1,
  "agent_id": "chimera-host-abcd1234",
  "version": "2.2.0",
  "capabilities": ["shell", "http_fetch", "web_search", "code_exec", "spawn_sub_agent"],
  "pid": 12345,
  "host": "alice-mbp",
  "reach": {
    "transport": "stdio",
    "command": ["chimera", "serve"]
  },
  "registered_at": "2026-05-19T14:32:00+00:00"
}
```

### Why a directory of files

- **Concurrency-safe by construction.** Each Chimera owns one file
  named after its agent_id. Two Chimeras starting at the same time
  don't collide.
- **Stale entries are trivially detected.** Use ``pid`` to check
  liveness (``os.kill(pid, 0)``); if the entry's ``host`` matches
  this host and the pid is dead, ``sweep_stale()`` ``unlink``s it.
- **Plain-text inspectable.** ``ls`` and ``cat`` are valid debug tools.
- **No service to run.** No daemon, no port, no auth. Filesystem
  permissions are the trust boundary.

### Lifecycle

- Start: ``serve_stdio`` calls ``a2a.registry.register(identity)``
  before entering the MCP read loop.
- Exit: a ``try/finally`` calls ``a2a.registry.forget(agent_id)``.
  This catches normal exits + SIGTERM (when wired). Hard kills leave
  stale entries — ``chimera peers sweep`` cleans them on demand.

### CLI

- ``chimera peers list`` — enumerate entries
- ``chimera peers forget <agent_id>`` — manual removal
- ``chimera peers sweep`` — drop entries whose pid (same host) is gone

## What v2.2 *doesn't* do

- **Cross-host discovery.** A directory works for co-located Chimeras
  only. Cross-host needs either a shared filesystem (NFS, Object
  Storage with FUSE) or a network registry (v2.x — likely HTTP +
  bearer-token auth, ADR-to-be).
- **Authentication.** A malicious local user with write access to the
  registry dir can plant fake entries. v2.2 trusts the filesystem;
  multi-tenant containers should mount their own dir.
- **Auto-dial.** Discovery doesn't automatically populate
  ``CHIMERA_MCP_SERVERS``. The MCP client still needs to be told
  which peers to dial. v2.3 will use the registry to drive auto-dial
  for swarm-KFM coordination.

## References

- [ADR 0006](0006-identity-handshake.md) — identity payload schema
- [chimera/a2a/registry.py](../../chimera/a2a/registry.py)
- [chimera/server/mcp_server.py](../../chimera/server/mcp_server.py) — register/forget around ``serve_stdio``
