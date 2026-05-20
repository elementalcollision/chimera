# ADR 0049 — Fix peer_name_from_tool for hyphenated peers (v4.27)

**Status:** Accepted (2026-05-19)

## Context

v4.26 surfaced a real bug: `peer_name_from_tool("mcp-chimera-a-shell")`
returned `"chimera"` instead of `"chimera-a"`. The original implementation
split on the first hyphen after `mcp-`, so any peer whose MCP server
name contained a hyphen silently bypassed the trust gate. The
PeerAwareDispatcher would then look up state for the wrong peer
name, get `None`, and DEGRADE (instead of evaluating the actual
peer's state and possibly REFUSING).

This was a **security-relevant** silent bypass — a peer in T0 LOCKED
with a hyphenated name would be downgraded to T1 dispatch instead of
refused outright. The v4.26 drill workaround was to rename the local
peer to `chimera_a`, but real MCP server names in production
configurations routinely use hyphens.

## Decision

`peer_name_from_tool` now accepts an optional `registry` parameter.
When supplied, it resolves the peer name by longest-prefix match —
walking candidate prefixes from longest to shortest and returning
the first one whose `mcp-<prefix>-chimera-identity` OR
`mcp-<prefix>-chimera-kfm-state` tool is registered (either
always-allowed peer tool is a sufficient signal that the prefix
names a real peer).

Without a registry the function keeps the old first-segment behaviour
for back-compat (unit tests, pure-string callers).

`PeerAwareDispatcher.dispatch` passes its own `self._registry` so the
gate now resolves hyphenated peers correctly.

## Validation

- The v4.26 trust-gating drill now uses the real `chimera-a` peer
  name (no underscore workaround). Both REFUSE and ALLOW paths still
  pass end-to-end.
- New unit tests in `tests/test_cross_agent_trust.py`:
  - `test_peer_name_from_tool_resolves_hyphenated_peer_via_registry`
    — asserts the bug is fixed when registry is supplied AND that
    without-registry behaviour is unchanged.
  - `test_peer_name_from_tool_registry_returns_none_for_unknown_peer`
    — non-registered peer returns None, so dispatcher falls through
    to non-peer pathway safely.
- Existing peer-dispatch unit tests pass unchanged because they
  register an `mcp-<peer>-chimera-kfm-state` tool, which the resolver
  now also accepts as a peer signal.
- Full suite: 525 passing, 5 skipped (was 523 / 5, +2 new).

## Non-goals

- **Tightening the always-allowed list.** Identity + kfm-state remain
  the only always-allowed peer tools ([ADR 0009](./0009-cross-agent-trust.md)). The resolver just
  uses their presence as a discovery signal.
- **DEGRADE-path drill.** Still a separate follow-up.
- **HTTP transport variant.** Still a separate follow-up.
