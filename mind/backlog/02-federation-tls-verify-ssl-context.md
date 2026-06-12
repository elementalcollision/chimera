---
goal: "Replace deprecated httpx verify=<str> with ssl.create_default_context in the federation TLS path"
files: chimera/scenarios/federation_drill.py chimera/tools/mcp_client.py
test: "-W error::DeprecationWarning tests/test_remote_federation_tls_drill.py"
base: main
done: false
---
httpx deprecated passing a certificate path as `verify=<str>`: "`verify=<str>`
is deprecated. Use `verify=ssl.create_default_context(cafile=...)` instead." Two
places in the federation TLS path do this:

- `chimera/scenarios/federation_drill.py` — `_wait_for_health` and
  `_check_anonymous_rejected` take `verify: bool | str` and pass it to
  `httpx.AsyncClient(verify=verify)`.
- `chimera/tools/mcp_client.py` — the `httpx_client_factory` built when
  `config.tls_ca` is set passes `verify=config.tls_ca`.

Change: when the value is a path (str), build it via
`ssl.create_default_context(cafile=<path>)` and pass that context as `verify`;
keep the `verify=True` (default certifi) behaviour for the bool case unchanged.

Ordering: run AFTER 01 (streamablehttp) has landed — the TLS drill also exercises
the MCP client, so its `-W error` gate stays red on the streamablehttp
deprecation until 01 is on `main`. The picker selects 01 first by filename order.

Acceptance: `chimera verify --test "-W error::DeprecationWarning tests/test_remote_federation_tls_drill.py"` is GREEN (with 01 already merged).
