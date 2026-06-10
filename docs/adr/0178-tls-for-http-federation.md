# ADR 0178 — TLS for the HTTP MCP transport

**Status:** Accepted (2026-06-10)

## Context

ADR 0175 fixed the bearer-token comparison (timing side-channel) but left
its explicit trigger open: the HTTP MCP server serves **cleartext**, so on
any non-loopback bind the bearer token — and every tool payload — crosses
the network sniffable. One captured request equals a stolen token, which
makes the v4.52 "non-loopback requires a token" guard security theatre
the moment the transport leaves localhost. ADR 0175's revisit trigger:
*"If federation ever moves off loopback, this ADR's cleartext-transport
caveat must be closed by a follow-up TLS ADR before that ships."* This is
that ADR, closed **before** any non-loopback deployment exists.

## Decision

### Server-side TLS, env-configured

Two new registry flags (declared in `chimera/config.py`, ADR 0176):

- `CHIMERA_TLS_CERT` — PEM certificate path
- `CHIMERA_TLS_KEY` — PEM private-key path

`_tls_config()` reads the pair and **fails closed**: one set without the
other, or a path that isn't a file, raises `TlsConfigError` rather than
silently falling back to cleartext (a typo'd cert path must not produce a
plaintext listener). `serve_http` passes the pair to uvicorn
(`ssl_certfile`/`ssl_keyfile`) and logs the bound scheme. Configuration is
env-only, consistent with every other knob in the system; no new CLI
options.

### Tightened bind policy

`_check_bind_security` (v4.52) now requires, for any non-loopback bind,
**both** a bearer token *and* TLS. Previously a token alone sufficed —
which protected against anonymous peers but not against the token itself
being sniffed. Loopback binds are unchanged (anonymous + cleartext remain
fine on-host, the current and recommended deployment). The existing
`CHIMERA_ALLOW_INSECURE_HTTP=1` escape hatch overrides both requirements
(CI / sandboxed networks), and the refusal message states exactly what is
missing.

This is a deliberate breaking change for any hypothetical
token-but-no-TLS non-loopback deployment; none exists (federation is
loopback-only today), which is precisely why the policy lands now.

### Client side

Peers dial `https://` URLs through httpx/MCP, which verifies certificates
against the system trust store by default. For self-signed deployments,
point the standard `SSL_CERT_FILE` env var at the CA/cert — no
Chimera-specific client knob until a real multi-host deployment shows the
need (avoids inventing config nobody uses).

## Verification

- `tests/test_tls_transport.py`: `_tls_config` matrix (unset / both /
  half-configured / missing file / whitespace), plus a **live HTTPS
  round-trip** — openssl self-signed cert, real uvicorn server on an
  OS-assigned port, httpx client: TLS handshake succeeds, `/health` 200,
  and bearer auth still gates `/mcp` over TLS (401 without, passes with).
- `tests/test_http_transport.py`: bind-policy matrix updated to the new
  contract — token-without-TLS refused (message names TLS),
  TLS-without-token refused (message names the token), token+TLS allowed,
  loopback and override behaviour unchanged.
- `validate_env` warns on a half-configured TLS pair at loop startup.

## Consequences

- Federation can now leave loopback without transmitting credentials in
  cleartext; the guard makes the secure path the only path that boots.
- Operators get fail-closed semantics: misconfigured TLS refuses to serve
  rather than degrading silently.
- Certificate provisioning/rotation is out of scope — self-signed pairs
  are fine for peer federation (peers can pin via `SSL_CERT_FILE`); a real
  CA story only matters if third-party clients ever appear.

## Falsification / revisit triggers

- If a real multi-host deployment needs mutual TLS (client certs) or
  per-peer cert pinning, extend this ADR — the identity-spoofing note in
  the 2026-06-10 review (agent IDs are not cryptographically bound) would
  be the driver.
- If `SSL_CERT_FILE` proves awkward for self-signed peer verification in
  practice, add `CHIMERA_TLS_CA` then, not before.
