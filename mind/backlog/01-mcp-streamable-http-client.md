---
goal: "Replace deprecated streamablehttp_client with streamable_http_client in the MCP HTTP client"
files: chimera/tools/mcp_client.py
test: "-W error::DeprecationWarning tests/test_federation_http_drill.py"
base: main
done: false
---
The MCP SDK deprecated `streamablehttp_client` in favour of
`streamable_http_client` ("Use `streamable_http_client` instead"). It is
imported and called in `chimera/tools/mcp_client.py` (`_open_session`).

Change: update the `from mcp.client.streamable_http import ...` import and the
call site to `streamable_http_client`. Keep the `# type: ignore` and behaviour
identical — this is a pure rename of the deprecated symbol.

Gate-visibility: the gate runs `test_federation_http_drill.py` (cleartext HTTP,
no TLS) under `-W error::DeprecationWarning`, so the deprecation is a hard
failure on `main` (RED) and the rename makes it pass (GREEN). This drill does
not touch the `verify=` TLS path, so it isolates this one deprecation.

Acceptance: `chimera verify --ruff chimera/tools/mcp_client.py --test "-W error::DeprecationWarning tests/test_federation_http_drill.py"` is GREEN.
