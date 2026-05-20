# ADR 0005 — Multi-agent architecture (v2.0)

**Status:** Accepted. Anchors v2.0. Successor entries codify each
v2.x iteration as it lands.

**Context:** v1 made Chimera autonomous in isolation. The v1.5 spike
([ADR 0004](0004-xenocomm-a2a.md)) wired Chimera as an MCP *client* of
Xenocomm. v2.0 flips the symmetry: Chimera now exposes its own MCP
*server* so peers can call it. Two Chimeras can talk to each other; an
operator can also point Claude Code / Cursor / Moltbot at a Chimera and
treat it as a callable tool surface.

## Decisions

### 1. Two-sided MCP

- **Client side** (existing, v1.0 Phase 3.3): `register_mcp_servers_from_env`
  reads `CHIMERA_MCP_SERVERS`, dials each, registers their tools under
  `mcp-<server>-<tool>`.
- **Server side** (new, v2.0): `chimera serve` starts an MCP stdio
  server that advertises a subset of Chimera's tool registry and
  dispatches inbound calls back through the existing OpenClaw-style
  policy pipeline.

Same dispatcher, same policy pipeline, same activity log. Peers are
just another caller. ACT (in-process) and peer calls share the audit
trail.

### 2. Default-deny tool exposure

No tool is reachable by peers unless explicitly listed in the
`CHIMERA_PEER_EXPOSED_TOOLS` env var (comma-separated tool names).
Empty/unset → zero tools advertised → peers see an empty `tools/list`.

This is the simplest opt-in mechanism. Per-tool `peer_exposable` flags
on `ToolEntry` are deliberately *not* added at v2.0 because env-only
operator control beats two-axis control (code + env) for the early
iteration. v2.x can promote this to `ToolEntry` once we have a real
use case for per-tool exposure decisions.

### 3. Trust context for peer calls

Peer-originated `tools/call` requests build a `DispatchContext` with:

- `trust_tier = "T1"` (supervised) at v2.0 — peer calls never default
  to higher than Chimera's own minimum operating tier. Local ACT calls
  use the live tier from `TrustManager`; peers are deliberately separate.
- `session_id = "peer"` — distinguishable from in-process ACT in the
  activity log.

v2.x will iterate: identify the peer, look up its tier (mutual
attestation), then choose the effective context tier as
`min(my_tier_for_peers, peer_attested_tier)`.

### 4. Stdio transport at v2.0

Peers launch Chimera as a subprocess. This matches the rest of the MCP
ecosystem and avoids the auth/TLS questions HTTP transport would open.

HTTP / SSE transports land in v2.1 once we have:

- Per-peer bearer-token auth.
- A way to bind to a network address sanely (Docker network vs
  loopback vs Internet — non-trivial).
- A way to advertise reachable endpoints in a peer registry.

### 5. Two Chimeras talking — operational shape

Chimera A starts its server:

```bash
CHIMERA_PEER_EXPOSED_TOOLS=shell,http_fetch chimera serve
```

Chimera B's `.env`:

```bash
CHIMERA_MCP_SERVERS='{
  "chimera-a": {
    "command": "chimera",
    "args": ["serve"],
    "env": {
      "CHIMERA_PEER_EXPOSED_TOOLS": "shell,http_fetch",
      "CHIMERA_MIND_DIR": "/path/to/a/mind",
      "CHIMERA_STATE_DIR": "/path/to/a/state"
    }
  }
}'
```

On B's first cycle, the existing MCP loader discovers
`mcp-chimera-a-shell` and `mcp-chimera-a-http_fetch` and registers them.
ACT can call them like any other tool.

## What v2.x will need

| Topic | Owner ADR | Target |
|---|---|---|
| Identity handshake — mutual attestation of agent_id, capabilities, KFM state | [ADR 0006](./0006-identity-handshake.md) | v2.1 |
| HTTP/SSE transport + bearer-token auth | [ADR 0007](./0007-peer-registry.md) | v2.1 |
| Peer registry / discovery (replaces hand-edited env) | [ADR 0008](./0008-swarm-kfm.md) | v2.2 |
| Swarm-KFM coordination (multi-agent ontology) | [ADR 0009](./0009-cross-agent-trust.md) | v2.3 |
| Alignment ceremony via Xenocomm's 5 strategies | [ADR 0010](./0010-peer-aware-dispatcher.md) | v2.3 |
| Emergence-aware protocol evolution | [ADR 0011](./0011-http-transport.md) | v2.4 |
| Cross-agent trust + per-peer tier mapping | [ADR 0012](./0012-inbound-attestation.md) | v2.4 |

This sequence is intentional: every later piece depends on identity
(2.1) and discovery (2.2) being real first. The Xenocomm SDK's
alignment + emergence work happens once Chimera can reliably *find*
peers and *prove who it is to them*.

## Consequences

- **No new runtime dependencies.** v2.0 uses the existing `mcp` SDK that
  Chimera's already shipping with for the client.
- **Default state is safe.** A freshly-built Chimera with no env config
  exposes no tools to peers.
- **The MCP server is single-connection.** Stdio means one peer per
  process. Multi-peer comes with HTTP in v2.1.
- **Activity log captures cross-agent calls.** `agent_activity_log` rows
  for peer-originated dispatches will show `session_id = "peer"`. Good
  audit hygiene for free.

## References

- [ADR 0001](0001-sdk-chimera-boundaries.md) §"Tool dispatch policy", §"MCP client"
- [ADR 0004](0004-xenocomm-a2a.md) §"What v2 will need"
- [chimera/server/mcp_server.py](../../chimera/server/mcp_server.py)
- Xenocomm SDK: [elementalcollision/xenocomm_sdk](https://github.com/elementalcollision/xenocomm_sdk)
