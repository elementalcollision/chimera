# ADR 0042 — Peer federation drill (v4.20)

**Status:** Accepted (2026-05-19)

## Context

The v2.x/v3.x peer-protocol work shipped a serious surface area —
identity handshake, KFM-state fetch, trust policy, protocol journal,
HTTP transport with bearer auth — but the only end-to-end exercise
we had was `chimera scenario two_chimera`, which just calls a peer's
shell tool. We have no test that drives the *full* protocol round
trip in CI. Peer-protocol bugs would only surface in production-ish
manual runs.

The user asked for a "peer federation drill" — two Chimera nodes,
one initiates a task, the other supplies a witness — to close that
gap before we start adding more peer-side features.

## Decision

A new scripted scenario, `chimera/scenarios/federation_drill.py`,
that exercises the protocol in anger:

1. **Spawn** Chimera-A as a subprocess (`uv run chimera serve` with
   isolated mind/state dirs and `CHIMERA_PEER_EXPOSED_TOOLS=shell`).
2. **Identity handshake** — `fetch_peer_identity` against the
   `mcp-chimera-a-chimera-identity` tool.
3. **KFM-state fetch** — `fetch_peer_kfm` against the
   `mcp-chimera-a-chimera-kfm-state` tool.
4. **Witness call** — Chimera-B pre-seeds a `research_target.md`
   into A's mind dir, then asks A's shell to `wc -l` it. The line
   count is parsed back and verified.
5. **Protocol journal** — every `mcp-chimera-a-*` tool currently in
   the registry is appended to B's per-peer JSONL via
   `record_observations_from_registry`.

Returned as a structured `FederationDrillResult` with explicit
`failures: list[str]` so callers can assert each step.

### CLI

`chimera scenario federation_drill` prints the result and exits
non-zero on failure.

### Test

`tests/test_federation_drill.py` runs the full drill end-to-end as
part of the default pytest run. Skips if `uv` isn't on PATH so it's
safe in minimal CI environments. Tagged `@pytest.mark.slow` and
declared in `pyproject.toml`'s pytest markers.

## What the drill catches today

- Identity tool unreachable / wrong shape.
- KFM-state JSON parsing regressions.
- Peer shell cwd / allow-list regressions (caught one during dev: the
  default cwd is the parent of mind+state, so the path must be
  prefixed `mind/<file>`).
- Protocol-journal observation writer breakage.

## Non-goals

- **Real model calls.** The drill is provider-agnostic — no
  API key required. Future work can extend it with a real `cross_critique`
  spanning a peer, but that's v4.2x territory.
- **Trust gating cases.** The drill runs with `DispatchContext()`
  defaults (T0). A second drill scenario for the T3+ gating path is
  worth adding when we touch that code next.
- **HTTP transport.** The drill uses stdio MCP. An HTTP variant with
  the bearer-auth middleware in the loop is a natural follow-up.
