# ADR 0012 — Inbound peer attestation (v2.7)

**Status:** Accepted. Anchors v2.7. The inbound complement to
[ADR 0009](0009-cross-agent-trust.md) / [ADR 0010](0010-peer-aware-dispatcher.md)
which handled the outbound half.

## Context

v2.0–v2.6 ran every inbound peer-typed MCP call at the flat
``DispatchContext(trust_tier="T1")`` baseline. There was no way for
Chimera to know *which* peer was calling — every connection was
treated identically. v2.6 added HTTP + bearer-token auth, which gives
us the missing primitive: a stable identifier (the token) per
incoming connection.

## Decision

### Per-peer tokens via ``CHIMERA_PEER_TOKENS``

A new env var carries a JSON object mapping token → peer-name:

```bash
CHIMERA_PEER_TOKENS='{"abc123": "chimera-alpha", "def456": "chimera-beta"}'
```

``CHIMERA_PEER_TOKEN`` (singular) from v2.6 still works — it's the
shared/anonymous-but-authenticated token. Both can coexist.

### contextvar propagates the attested peer

``chimera.server.peer_auth.current_peer`` is a ``contextvars.ContextVar[str | None]``.
The HTTP bearer middleware sets it after a successful token match, then
``reset`` s it in a ``finally``. Anyone deeper in the same async task —
including the MCP ``call_tool`` handler — can read it. No thread-locals,
no global state.

### Inbound dispatch context, by case

| Inbound case | trust_tier | session_id |
|---|---|---|
| Anonymous (no token configured) | T1 | ``"peer"`` |
| Shared token only (no peer-name) | T1 | ``"peer"`` |
| Per-peer token → peer in registry, policy says ALLOW | T2 | ``"peer:<name>"`` |
| Per-peer token → peer in registry, policy says DEGRADE | T1 | ``"peer:<name>"`` |
| Per-peer token → peer in registry, policy says REFUSE | (error response) | — |
| Per-peer token → peer NOT in registry | T1 | ``"peer:<name>"`` |

T2 ("UNLOCKED") is the ceiling for inbound. Even an ALLOW decision
doesn't grant T3+ — that requires a stronger signal than "I know who
they are." Local ACT runs at the live tier from TrustManager (up to T5);
peers cap at T2.

### Why contextvars, not Starlette state

Starlette's ``request.state`` lives on the HTTP request scope; by the
time the MCP session manager invokes our ``call_tool`` handler, we're
several layers below the request. ``contextvars`` propagate through
``await`` automatically and survive every awaitable in the call stack
of the same task. This was the cleanest mechanism the stdlib offers
for this exact use case.

## What v2.7 *doesn't* do

- **Doesn't sign anything.** Tokens are still shared secrets, not
  signed claims. The "attestation" here is "you presented the token
  I expected for peer X." A cryptographic authority (peer registry as
  identity provider) is a future ADR.
- **Doesn't enrich peer state from the wire.** ``lookup_peer_state``
  reads the v2.2 registry, which carries identity + capabilities but
  NOT live KFM/drift. The fallback assumes ``plan_kfm_state="STABLE"``,
  ``trust_tier_int=2``, ``last_drift_score=0`` — enough for the policy
  to allow well-registered peers. A future ADR will have peers write
  their kfm snapshot into the registry alongside their identity, so
  inbound decisions can be drift-aware.
- **Doesn't gate stdio connections.** Stdio is single-peer-per-process
  with no auth concept; v2.7's contextvar simply stays unset on the
  stdio path. v2.0's flat T1 still applies there.

## References

- [ADR 0006](0006-identity-handshake.md) — identity payload schema
- [ADR 0007](0007-peer-registry.md) — peer registry the lookup uses
- [ADR 0009](0009-cross-agent-trust.md) — :class:`PeerTrustPolicy` reused
- [ADR 0011](0011-http-transport.md) — HTTP middleware where attestation runs
- [chimera/server/peer_auth.py](../../chimera/server/peer_auth.py)
- [chimera/server/http_server.py](../../chimera/server/http_server.py) — middleware
- [chimera/server/mcp_server.py](../../chimera/server/mcp_server.py) — call_tool reads contextvar
