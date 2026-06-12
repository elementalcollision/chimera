---
goal: "Migrate the federation HTTP/TLS client to the new MCP SDK streamable_http_client(http_client=...) API + ssl-context verify"
files: chimera/tools/mcp_client.py chimera/scenarios/federation_drill.py
test: "-W error::DeprecationWarning tests/test_remote_federation_tls_drill.py"
base: main
done: true  # done directly (not via CRAWL) 2026-06-12 — see crawl-first-run note
---
NOT a rename (the first CRAWL run proved this — see
mind/research/crawl-first-run-2026-06-12.md). The MCP SDK's
`streamable_http_client` CONSOLIDATED the old `streamablehttp_client`
signature: old `(url, headers=, timeout=, httpx_client_factory=, auth=, …)`
→ new `(url, *, http_client: httpx.AsyncClient | None, terminate_on_close=)`.
Everything (headers, TLS verify, timeout) now goes into one
`httpx.AsyncClient` you build and pass as `http_client=`.

Two coupled changes (the TLS drill exercises both files; fixing one alone
leaves the gate red):

1. `chimera/tools/mcp_client.py` `_open_session`: build a single
   `httpx.AsyncClient(headers=<bearer or None>, verify=<ssl context or True>,
   timeout=30)` and call `streamable_http_client(url=config.url,
   http_client=client)`. This replaces BOTH the deprecated symbol AND the
   `verify=config.tls_ca` (build the context with
   `ssl.create_default_context(cafile=config.tls_ca)` when tls_ca is set).
2. `chimera/scenarios/federation_drill.py` `_wait_for_health` /
   `_check_anonymous_rejected`: replace `httpx.AsyncClient(verify=<str>)`
   with `verify=ssl.create_default_context(cafile=<path>)` when the value is
   a path; keep `verify=True` (certifi) for the bool case.

Acceptance: `chimera verify --test "-W error::DeprecationWarning tests/test_remote_federation_tls_drill.py"` is GREEN, and the cleartext drill
(`tests/test_federation_http_drill.py`) still passes.
