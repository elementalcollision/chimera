# ADR 0048 — Trust-gating federation drill (v4.26)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0042](./0042-peer-federation-drill.md) (v4.20) shipped a real two-process federation drill but used
the base `Dispatcher` — the trust-policy gate ([ADR 0009](./0009-cross-agent-trust.md) / 0010,
v2.4 / v2.5) was never exercised end-to-end. Trust-policy code has
sat in production-ready state since v2.5 with only unit tests
covering it. The non-goal called out a follow-up: drive the
`PeerAwareDispatcher` under both ALLOW and REFUSE conditions.

## Decision

Add `run_federation_trust_drill(peer_root)` alongside the existing
`run_federation_drill`. Same subprocess spawn, but uses
`PeerAwareDispatcher` and runs two sub-runs against the same peer
root:

1. **Locked** — no `trust_state.json`. Peer's `chimera-kfm-state`
   tool reports `trust_tier_int=0` (T0 LOCKED). Policy refuses.
   `PeerCallRefused` is caught.
2. **Healthy** — pre-seeds `state/trust_state.json` with
   `current_tier=2` before spawning. Peer reports T2. Policy allows.
   Shell call succeeds.

Decision per sub-run is read from `peer_trust_journal` (the
journal-of-truth) rather than inferred from exception type — this
distinguishes ALLOW from DEGRADE, which both succeed silently.

### CLI

`chimera scenario federation_trust_drill` reports both decisions and
the journal record count.

### Test

`tests/test_federation_trust_drill.py::test_trust_drill_refuses_locked_peer_and_allows_healthy`
runs end-to-end as part of pytest. Marked `slow`; skips without `uv`.

## Bug surfaced and worked around

`peer_name_from_tool("mcp-chimera-a-shell")` returns `"chimera"`,
not `"chimera-a"` — it splits on the first hyphen after `mcp-`. Any
peer whose MCP server name contains a hyphen silently bypasses the
trust gate (DEGRADE on a None peer-state lookup, not REFUSE). The
drill works around this by renaming the local peer to `chimera_a`.
**Filed as v4.27 follow-up** — needs a real fix to
`peer_name_from_tool` to support hyphens via a known-registry lookup.

## Tests

Full suite: 523 passing, 5 skipped (was 522 / 5, +1 new). The
existing `test_federation_drill.py` was updated to match the renamed
peer (`mcp-chimera_a-*`).

## Non-goals

- **DEGRADE path drill.** Driving DEGRADE explicitly (e.g.
  `trust_tier_int=1`) is straightforward — not in this slice.
- **HTTP transport variant.** Still TODO from [ADR 0042](./0042-peer-federation-drill.md).
- **The peer-name parsing fix.** Tracked separately as v4.27.
