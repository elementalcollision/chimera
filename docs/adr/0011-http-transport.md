# ADR 0011 — HTTP/SSE transport for chimera serve (v2.6)

**Status:** Accepted. Anchors v2.6. Originally listed in
[ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need" for v2.1.

## Context

Stdio transport (v2.0) is a single-peer-per-process medium. Two
Chimeras can talk only if one spawns the other as a subprocess.
For real multi-peer swarms, peers must dial a long-running address.

The MCP SDK ships ``mcp.server.streamable_http_manager`` (server) and
``mcp.client.streamable_http`` (client) implementing MCP's HTTP+SSE
transport. v2.6 wires both ends into Chimera.

## Decision

### Server: ``chimera serve --http``

A new CLI flag launches an ASGI app (Starlette + Uvicorn) wrapping the
existing ``Server`` instance via :class:`StreamableHTTPSessionManager`.

```bash
CHIMERA_PEER_TOKEN=abc123 \
CHIMERA_PEER_EXPOSED_TOOLS=shell \
chimera serve --http --host 0.0.0.0 --port 8765
```

Endpoints:

- ``/health`` — returns ``chimera ok`` (200). No auth required.
- ``/mcp`` — the MCP streamable HTTP endpoint. Bearer-auth gated.

Auth is bearer-token via the ``Authorization: Bearer <token>`` header.
The expected token comes from ``CHIMERA_PEER_TOKEN``. If unset, the
server logs a loud warning and allows anonymous access (intended only
for ``127.0.0.1`` local dev). Production deployments MUST set the env.

The Starlette middleware rejects any non-``/health`` request without a
valid bearer with 401.

### Client: extended ``CHIMERA_MCP_SERVERS`` schema

The existing JSON config gains a ``transport`` field:

```json
{
  "stdio-peer":  { "transport": "stdio", "command": "chimera", "args": ["serve"] },
  "http-peer":   { "transport": "http",  "url": "http://10.0.0.5:8765/mcp",
                   "token": "abc123" }
}
```

Defaults to ``"stdio"`` for backward compatibility with v2.0–v2.5
configs. The MCP client (``chimera.tools.mcp_client``) branches on
``transport`` inside ``_open_session()`` and uses
``mcp.client.streamable_http.streamablehttp_client`` for the HTTP path.
Per-call ephemeral sessions remain the model — same as stdio. Persistent
sessions for low-latency back-to-back calls is a later optimisation.

### Bind host defaults to loopback

``--host 127.0.0.1`` by default. Operators must explicitly opt into
``--host 0.0.0.0`` to expose. Avoids accidentally publishing tools to
the LAN.

## What v2.6 *doesn't* do

- **No TLS termination.** Put a reverse proxy (Caddy/Traefik/nginx) in
  front if you need HTTPS. Native TLS in Chimera is out of scope —
  the proxy use-case is well-served by existing tooling.
- **No per-peer token rotation.** A single bearer is configured; all
  peers share it. Per-peer tokens come when there's a peer registry
  that issues them.
- **No rate-limiting / DOS protection.** The Starlette/Uvicorn stack is
  fine for trusted swarms; for hostile networks add a proxy with
  rate-limit middleware.

## References

- [ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need" — original plan
- [chimera/server/http_server.py](../../chimera/server/http_server.py)
- [chimera/tools/mcp_client.py](../../chimera/tools/mcp_client.py) — `_open_session` transport branch
- MCP spec: streamable HTTP — https://modelcontextprotocol.io/specification/server/transports
