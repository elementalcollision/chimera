# ADR 0004 — Xenocomm / A2A integration (spike)

**Status:** Proposed (spike). Closes the v2 deferral in [ADR 0001](0001-sdk-chimera-boundaries.md)
§"A2A / inter-agent comms" with a *config-only* path for v1.5; full
spec-level work is still v2.

**Context:** [elementalcollision/xenocomm_sdk](https://github.com/elementalcollision/xenocomm_sdk)
ships an MCP server (`xenocomm_mcp`) exposing tools for:

- agent identity + KFM lifecycle (`kfm_lifecycle.py`)
- alignment verification (5 formal strategies; `alignment.py`)
- emergence management (safe protocol evolution; `emergence.py`)
- observation (`observation.py`)
- dashboard surface (`dashboard.py`)

Chimera v1.0 Phase 3.3 already ships an MCP stdio client that registers
tools under an `mcp-<server>-<tool>` prefix and dispatches calls back to
the originating server.

**Decision:** for v1.5, treat Xenocomm as an external MCP peer. No new
Python module is added to Chimera. Instead:

1. Operators set `CHIMERA_MCP_SERVERS` to include a `xenocomm` entry
   pointing at `python -m xenocomm_mcp` (or the `uvx xenocomm-mcp`
   variant).
2. On Chimera's first cycle, the existing MCP loader discovers the
   xenocomm tools and registers them under `mcp-xenocomm` toolset.
3. ACT picks them up like any other tool. The dispatcher's policy
   pipeline (OpenClaw layers) gates them per session / trust tier.

**Config example.** Add to `.env`:

```bash
CHIMERA_MCP_SERVERS='{
  "xenocomm": {
    "command": "uvx",
    "args": ["xenocomm-mcp"]
  }
}'
```

Or, if you prefer a pinned source checkout:

```bash
CHIMERA_MCP_SERVERS='{
  "xenocomm": {
    "command": "python",
    "args": ["-m", "xenocomm_mcp"],
    "env": {
      "PYTHONPATH": "/path/to/xenocomm_sdk/mcp_server"
    }
  }
}'
```

**Two Chimeras talking.** A pair (or more) of Chimera instances can run
their own `xenocomm_mcp` server and dial each other's tools. v1.5
doesn't include peer discovery, identity handshake, or alignment
ceremony — those become real code in v2 once the surface stabilises.

## What v1.5 ships

1. This ADR.
2. [chimera/a2a/](../../chimera/a2a/) — a thin Python helper namespace:
   - `chimera.a2a.identity.AgentIdentity` — host + agent_id + KFM state
     advertised to peers when Chimera hosts its own MCP surface
   - `chimera.a2a.peers.list_xenocomm_tools(registry)` — convenience to
     enumerate tools registered under the `mcp-xenocomm` toolset
3. `chimera a2a peers` CLI — shows xenocomm tools the running Chimera
   has discovered.

No tests against a live Xenocomm server at v1.5 — that requires the SDK
installed; left for the operator to verify in their environment.

## What v2 will need

- **Peer discovery.** Today operators hand-configure each peer's MCP
  endpoint. v2 needs a registry (or gossip layer) so Chimera can find
  peers without hand-editing env.
- **Identity handshake.** Per Xenocomm's alignment strategies — Chimera
  must respond truthfully when a peer asks "who are you, what KFM state
  are you in, what capabilities do you advertise?"
- **Emergence-aware protocol evolution.** EmergenceManager mediates
  protocol drift between peers. Wiring this requires Chimera surfacing
  its drift state to the peer.
- **Multi-agent KFM coordination.** Today every Chimera is its own
  KFM machine. With peers, a "swarm KFM" emerges — `MARRIED` peers
  share state, `DEPRECATED` peers stop advertising. Decisions about
  multi-agent ontology stay in a future ADR.
- **Trust gating.** A peer's calls into Chimera should be gated by
  Chimera's trust tier and the peer's identity. Cross-references
  [ADR 0001](0001-sdk-chimera-boundaries.md) §"Tool dispatch policy"
  and the v1.3 trust system.

## References

- Xenocomm SDK: [elementalcollision/xenocomm_sdk](https://github.com/elementalcollision/xenocomm_sdk)
- [ADR 0001](0001-sdk-chimera-boundaries.md) §"MCP client", §"A2A / inter-agent comms"
- [pillar-positioning.md](../research/pillar-positioning.md) — village KFM operator lifecycle (informs swarm-KFM design)
