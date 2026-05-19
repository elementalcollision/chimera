# ADR 0006 — Peer identity handshake (v2.1)

**Status:** Accepted. Anchors v2.1. Sits between [ADR 0005](0005-multi-agent-architecture.md)
(two-sided MCP) and the future v2.2 peer-registry work.

## Context

v2.0 lets two Chimeras talk: A serves an MCP surface, B dials in. But
B has no canonical way to know *which Chimera it's talking to*. The
peer's filesystem (the only datum available in v2.0) could be anything.
Before any meaningful trust or policy decision can be peer-typed (a
v2.4 concern), there has to be a stable handshake that surfaces an
attested identity payload.

## Decision

Every Chimera MCP server unconditionally advertises a tool named
``chimera-identity``. Its toolset is ``peer``. Its semantics:

- **Inputs:** none.
- **Returns:** a JSON-stringified
  :class:`chimera.a2a.identity.AgentIdentity` (``agent_id``, ``version``,
  ``role``, ``capabilities``).
- **Side-effects:** none — pure read.
- **Allow-list bypass:** the tool is exposed regardless of
  ``CHIMERA_PEER_EXPOSED_TOOLS``. Operators cannot turn it off; it's
  the handshake target.
- **Stable name:** ``chimera-identity``. Peers can hardcode it.

After Chimera-B's MCP client connects to Chimera-A, B's first call
SHOULD be to ``mcp-<A>-chimera-identity``. The returned payload is
opaque to v2.1 — it gets logged, but v2.1 doesn't yet act on it.
v2.4's cross-agent trust will read this same payload to decide A's
effective trust tier when calling B.

## Why a tool and not a resource

MCP supports both ``tools/*`` and ``resources/*`` surfaces. Identity
*is* arguably a resource — but tools have one decisive practical
advantage at v2.1: every Chimera MCP client (v1.0) already routes
through the existing ``Dispatcher``. Resources would need a parallel
wire path. Tool minimises the change surface; we can promote to a
resource in v2.x if the semantic mismatch starts causing pain.

## Public surface

```python
# chimera/a2a/peers.py
def list_peer_chimeras(registry=None) -> list[str]: ...
async def fetch_peer_identity(peer_name, *, registry=None) -> dict: ...
```

- ``list_peer_chimeras`` enumerates server names by finding registered
  tools that end in ``-chimera-identity`` (a deterministic fingerprint
  of v2.1+ peers).
- ``fetch_peer_identity(peer_name)`` calls ``mcp-<peer_name>-chimera-identity``
  through the existing dispatcher and JSON-parses the response.

## Verification

The ``two_chimera`` scenario (introduced in v2.0) is extended to call
``fetch_peer_identity`` against the peer it just launched. Pass criterion:
the returned dict carries ``role == "chimera"`` and a non-empty
``agent_id`` matching ``chimera-…``.

## What v2.1 *doesn't* do

- **No signing.** The identity payload is unsigned; a malicious peer
  could lie. Signing lands when there's an actual identity authority
  (a v2.2+ peer registry can issue/verify tokens).
- **No peer-typed trust decisions.** v2.1 surfaces identity; v2.4 acts
  on it.
- **No HTTP/SSE.** Stdio only, per ADR 0005.

## References

- [ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need"
- [chimera/server/identity_tool.py](../../chimera/server/identity_tool.py)
- [chimera/a2a/peers.py](../../chimera/a2a/peers.py)
