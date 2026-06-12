"""Remote federation drill over TLS — ADR 0178 dispatch-over-TLS validation.

The TLS *serving* path (`serve_http` + `_tls_config`) is unit-covered by
tests/test_tls_transport.py; what was unvalidated until this drill is a full
**federation dispatch over TLS**: three real `chimera serve --http` peers
serving HTTPS with a self-signed cert, the MCP client pinning that cert as
its trust root (`MCPServerConfig.tls_ca` → httpx ``verify``), and the entire
ADR 0167/0168 stack — trust gate, two-choice selection, connectivity gauge —
running across the encrypted transport.

Also asserts the negative: a client that does NOT trust the cert fails TLS
verification (the cleartext-sniffing protection is real, not decorative).

Skipped without ``uv`` or ``openssl`` on PATH; marked ``slow``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chimera.scenarios import run_remote_federation_drill

pytestmark = pytest.mark.slow


def _missing(binary: str) -> bool:
    return shutil.which(binary) is None


@pytest.fixture
def cert_pair(tmp_path: Path) -> tuple[str, str]:
    if _missing("openssl"):
        pytest.skip("openssl not available")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-days", "1", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return str(cert), str(key)


def test_remote_federation_drill_over_tls(tmp_path: Path, cert_pair):
    if _missing("uv"):
        pytest.skip("uv not on PATH; cannot spawn `uv run chimera serve --http`")
    cert, key = cert_pair

    result = run_remote_federation_drill(
        tmp_path / "fed", tls_cert=cert, tls_key=key
    )

    assert result.ok, f"TLS drill failed: {result.failures}"
    assert result.health_ok

    # Same ADR 0167/0168 properties as the cleartext drill — now over HTTPS.
    assert sorted(result.allow_peers) == ["alpha", "beta"]
    assert result.refuse_peers == ["gamma"]
    assert set(result.selection_spread).issubset({"alpha", "beta"})
    assert len(result.selection_spread) == 2
    c = result.connectivity
    assert c is not None and c["isolated_nodes"] == 1


@pytest.mark.asyncio
async def test_untrusted_client_fails_tls_verification(tmp_path: Path, cert_pair):
    """A client without the pinned CA must FAIL the handshake — proves the
    transport is actually encrypted+verified, not silently downgraded."""
    if _missing("uv"):
        pytest.skip("uv not on PATH")
    cert, key = cert_pair

    import httpx

    from chimera.scenarios.federation_drill import _spawn_peer, _wait_for_health

    proc, _name, url, _token = await _spawn_peer(
        tmp_path / "solo", agent_id="alpha", tier=4, tls_cert=cert, tls_key=key
    )
    try:
        assert url.startswith("https://")
        assert await _wait_for_health(url, timeout_s=20.0, verify=cert)
        # Default trust store does not contain the self-signed cert → the
        # handshake must fail rather than fall back to cleartext.
        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(url.rstrip("/") + "/healthz")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
