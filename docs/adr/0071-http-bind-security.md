# ADR 0071 — HTTP bind security guard (v4.52)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0064](./0064-container-bootstrap.md) (v4.45) ships a Docker compose that binds
`chimera serve --http` to `0.0.0.0:8765`. The HTTP server has had
optional bearer-auth since v2.6 ([ADR 0011](./0011-http-transport.md)), but `CHIMERA_PEER_TOKEN`
was advisory — if unset, the server logged a warning and accepted
anonymous traffic. Fine for local dev. Not fine for the container
case, which exposes to whatever network Docker is on.

`chimera doctor` already flagged `[!] http auth: neither
CHIMERA_PEER_TOKEN nor CHIMERA_PEER_TOKENS set; HTTP server will
allow anonymous (local-dev only)`. The warning was right; the
behaviour was wrong.

## Decision

Promote the warning to a startup-time refusal when the bind is
non-loopback.

### `_check_bind_security(host: str) -> None`

Module-level guard in `chimera/server/http_server.py`. Raises
`InsecureHttpBindError` when ALL of the following hold:

- `host` is not one of `{127.0.0.1, ::1, localhost}` (case-insensitive)
- `CHIMERA_PEER_TOKEN` is unset
- `CHIMERA_PEER_TOKENS` is unset
- `CHIMERA_ALLOW_INSECURE_HTTP` is not set to `1` / `true` / `yes`

The error message tells the operator exactly which three remediations
are available:

```
refusing to bind chimera serve --http to non-loopback host '0.0.0.0'
without auth. Set CHIMERA_PEER_TOKEN (single token) or
CHIMERA_PEER_TOKENS (JSON map), OR pass --host 127.0.0.1 for
loopback-only, OR set CHIMERA_ALLOW_INSECURE_HTTP=1 to override
(not recommended).
```

`serve_http` calls the guard before `assert_no_errors()` and before
any uvicorn setup, so the failure is fast and obvious.

### Compose update

The docker-compose annotation now explicitly notes that the
0.0.0.0 bind requires `CHIMERA_PEER_TOKEN` in `.env`. Operators
who want loopback-only can change `--host 0.0.0.0` to `127.0.0.1`
and the guard relaxes — same behaviour as local-venv dev.

## Tests

`tests/test_http_transport.py` — 6 new tests:

- `test_is_loopback_recognises_common_loopback_hosts` — including
  case-insensitive `LOCALHOST` and rejecting `0.0.0.0` / public IPs.
- `test_check_bind_security_refuses_non_loopback_without_token` —
  raises `InsecureHttpBindError` with the expected hint.
- `test_check_bind_security_allows_non_loopback_with_token` — single
  token unblocks.
- `test_check_bind_security_allows_non_loopback_with_token_map` — the
  v2.6 multi-token JSON map also satisfies the guard.
- `test_check_bind_security_override_with_allow_insecure` —
  explicit insecure override works.
- `test_check_bind_security_allows_loopback_without_token` —
  loopback bind doesn't need a token.

The guard is extracted as a sync function so tests don't have to
boot uvicorn.

Full suite: **576 passing**, 5 skipped (+6 new).

## Non-goals

- **TLS termination.** Still belongs in a reverse proxy (caddy /
  nginx / traefik). The guard only ensures auth is in place; it
  doesn't add encryption.
- **Token rotation / expiry.** Outside this slice.
- **mTLS.** Outside this slice.
