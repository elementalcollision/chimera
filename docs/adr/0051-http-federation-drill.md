# ADR 0051 — HTTP transport federation drill (v4.29)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0011](./0011-http-transport.md) (v2.6) shipped HTTP/SSE as the second MCP transport with
`_BearerAuthMiddleware` enforcing `Authorization: Bearer <token>`
on every non-`/health` request. Until now the only end-to-end
exercise of the HTTP path was a stdio-equivalent demo in the
two_chimera scenario. We had no test that:

- actually spawns `chimera serve --http` as a subprocess,
- waits for the server to come up,
- proves anonymous /mcp requests are rejected,
- and round-trips identity / KFM / a peer tool via the HTTP MCP
  client.

The federation-drill series (v4.20, v4.26, v4.28) closed the stdio
trust gaps; HTTP was the remaining open transport gap.

## Decision

`run_federation_http_drill(peer_root)`:

1. Pick a free ephemeral port via `socket.bind(("127.0.0.1", 0))`.
2. Generate a random bearer token (`secrets.token_hex(8)`).
3. Spawn `uv run chimera serve --http --host 127.0.0.1 --port <p>`
   with `CHIMERA_PEER_TOKEN=<token>` and isolated mind/state dirs.
4. Poll `/healthz` until 200 (15s timeout).
5. POST `/mcp` without a token, assert 401/403.
6. Register an `MCPServerConfig(transport="http", url=…, token=…)`
   and run identity, KFM-state, and shell witness through the
   normal MCP client path.
7. Terminate the subprocess in `finally` (3s timeout, then kill).

### Test

`tests/test_federation_http_drill.py::test_http_drill_round_trip_with_bearer_auth`
runs end-to-end as part of pytest. Slow-marked; skips without
`uv` on PATH. ~1s wall-clock on dev hardware.

## What it catches

- `_BearerAuthMiddleware` failing open (anonymous /mcp accepted).
- HTTP MCP session establishment regressions.
- Identity / KFM-state / peer-shell schema changes that would break
  cross-transport parity with stdio.

## Tests

Full suite: 526 passing, 5 skipped (was 525 / 5, +1 new).

## Non-goals

- **HTTP trust-gating variant.** Combining v4.26/v4.28 with HTTP
  transport is a natural next slice; not in v4.29 to keep scope
  tight.
- **CHIMERA_PEER_TOKENS multi-token map.** Drill uses the single
  CHIMERA_PEER_TOKEN env. Multi-tenant token mapping is a separate
  test path.
- **TLS / cert pinning.** HTTP only; local-dev binding.
