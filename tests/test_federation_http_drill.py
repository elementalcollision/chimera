"""v4.29 — HTTP transport federation drill integration test.

Spawns `uv run chimera serve --http` as a subprocess on a free
ephemeral port with a random bearer token. Verifies:

  - The HTTP server comes up (poll /healthz).
  - Anonymous /mcp requests are rejected by _BearerAuthMiddleware.
  - The MCP client can authenticate and run identity / KFM / shell
    over the HTTP transport.

Skipped without ``uv`` on PATH; marked ``slow``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chimera.scenarios import run_federation_http_drill


pytestmark = pytest.mark.slow


def _have_uv() -> bool:
    return shutil.which("uv") is not None


def test_http_drill_round_trip_with_bearer_auth(tmp_path: Path):
    if not _have_uv():
        pytest.skip("uv not on PATH; cannot spawn `uv run chimera serve --http`")

    result = run_federation_http_drill(tmp_path / "peer")

    assert result.ok, f"drill failed: {result.failures}"
    assert result.health_ok
    assert result.auth_rejected_anonymous, (
        "anonymous /mcp request was not rejected — bearer auth bypass?"
    )
    assert result.identity is not None
    assert result.identity.get("role") == "chimera"
    assert result.kfm is not None
    assert "cycle" in result.kfm
    assert result.witness_lines == 6
