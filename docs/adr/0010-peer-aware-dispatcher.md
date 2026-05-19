# ADR 0010 — PeerAwareDispatcher (v2.5)

**Status:** Accepted. Anchors v2.5. Closes the "wire the policy in"
follow-up from [ADR 0009](0009-cross-agent-trust.md).

## Context

v2.4 shipped :class:`PeerTrustPolicy` and :class:`PeerStateCache` as
pure modules with unit tests. The ADR explicitly deferred the wiring
question — "the right shape comes after we have one concrete call
site to fit it to." v2.5 picks that shape.

## Decision: subclass the dispatcher

A new :class:`PeerAwareDispatcher` in ``chimera/a2a/peer_dispatch.py``
extends :class:`chimera.tools.Dispatcher`. It overrides ``dispatch()``
to insert a pre-flight check for any tool whose name matches the
``mcp-<peer>-…`` prefix:

| Case | Action |
|---|---|
| Not an mcp-* tool | super().dispatch() — unchanged |
| ``mcp-<peer>-chimera-identity`` | super().dispatch() — always-allowed |
| ``mcp-<peer>-chimera-kfm-state`` | super().dispatch() — always-allowed |
| Any other mcp-<peer>-* | Run policy, then ALLOW / DEGRADE / REFUSE |

State fetching uses the parent class's ``dispatch()`` directly (one
class-level ``super().dispatch()`` call to ``mcp-<peer>-chimera-kfm-state``).
This avoids recursing into our own policy gate when fetching state.

DEGRADE means the call proceeds but with a freshly-built
``DispatchContext(trust_tier="T1", session_id=ctx.session_id, ...)``.
REFUSE raises :class:`PeerCallRefused` (subclass of
:class:`chimera.tools.ToolDenied`) so existing exception handlers in
ActExecutor catch it naturally.

### Why subclass instead of decorator / inline in Dispatcher

- **Subclass** keeps the base ``Dispatcher`` minimal — it's still the
  reusable in-process tool dispatcher with no A2A baggage.
- **A decorator** would have to wrap an instance and re-export every
  method; clunkier for the few extra LOC saved.
- **Inline** would couple every consumer of the base ``Dispatcher`` to
  A2A concepts even when they don't have peers (tests, ad-hoc scripts).
  Bad coupling.

## Wiring

- :class:`chimera.core.loop.ChimeraLoop` constructs a
  :class:`PeerAwareDispatcher` by default.
- :class:`chimera.core.act.ActExecutor.from_env` constructs one too
  when its caller passes ``dispatcher=None``.
- Code that wants the base dispatcher (e.g. unit tests for tools that
  don't touch peers) continues to construct ``Dispatcher`` directly.

## What v2.5 *doesn't* do

- **Doesn't change inbound behaviour.** Inbound peer calls still run
  with ``DispatchContext(trust_tier="T1")`` from v2.0; mutual
  attestation stays v2.x.
- **Doesn't sign anything.** Peer-advertised state is unsigned.

## References

- [ADR 0009](0009-cross-agent-trust.md) §"What v2.4 doesn't do" — the
  follow-up promise this ADR keeps.
- [chimera/a2a/peer_dispatch.py](../../chimera/a2a/peer_dispatch.py)
- [chimera/a2a/trust_policy.py](../../chimera/a2a/trust_policy.py)
