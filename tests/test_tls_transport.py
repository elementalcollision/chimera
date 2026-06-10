"""TLS for the HTTP MCP transport (ADR 0178).

Covers the _tls_config() reader, the tightened bind policy, and — marked
slow — a real HTTPS round-trip against a uvicorn server using an
openssl-generated self-signed certificate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chimera.server.http_server import TlsConfigError, _tls_config


@pytest.fixture
def cert_pair(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-days", "1", "-subj", "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


# ── _tls_config ─────────────────────────────────────────────


def test_tls_config_unset_is_disabled(monkeypatch):
    monkeypatch.delenv("CHIMERA_TLS_CERT", raising=False)
    monkeypatch.delenv("CHIMERA_TLS_KEY", raising=False)
    assert _tls_config() == (None, None)


def test_tls_config_both_set_and_existing(monkeypatch, cert_pair):
    cert, key = cert_pair
    monkeypatch.setenv("CHIMERA_TLS_CERT", str(cert))
    monkeypatch.setenv("CHIMERA_TLS_KEY", str(key))
    assert _tls_config() == (str(cert), str(key))


@pytest.mark.parametrize("set_var", ["CHIMERA_TLS_CERT", "CHIMERA_TLS_KEY"])
def test_tls_config_half_configured_raises(monkeypatch, tmp_path, set_var):
    """A half-configured pair must refuse loudly, not fall back to
    cleartext."""
    monkeypatch.delenv("CHIMERA_TLS_CERT", raising=False)
    monkeypatch.delenv("CHIMERA_TLS_KEY", raising=False)
    some_file = tmp_path / "x.pem"
    some_file.touch()
    monkeypatch.setenv(set_var, str(some_file))
    with pytest.raises(TlsConfigError, match="must be set together"):
        _tls_config()


def test_tls_config_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIMERA_TLS_CERT", str(tmp_path / "nope.pem"))
    monkeypatch.setenv("CHIMERA_TLS_KEY", str(tmp_path / "alsonope.pem"))
    with pytest.raises(TlsConfigError, match="does not exist"):
        _tls_config()


def test_tls_config_whitespace_treated_as_unset(monkeypatch):
    monkeypatch.setenv("CHIMERA_TLS_CERT", "  ")
    monkeypatch.setenv("CHIMERA_TLS_KEY", "")
    assert _tls_config() == (None, None)


# ── live HTTPS round-trip ───────────────────────────────────


@pytest.mark.slow
@pytest.mark.asyncio
async def test_https_round_trip_with_self_signed_cert(
    monkeypatch, tmp_path, cert_pair
):
    """Boot the real ASGI app under uvicorn with TLS and verify (1) an
    HTTPS request succeeds and (2) bearer auth still gates /mcp."""
    import asyncio

    import httpx
    import uvicorn

    from chimera.server.http_server import build_http_app
    from chimera.server.mcp_server import ChimeraMCPServer

    cert, key = cert_pair
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "tls-drill-token")

    app = build_http_app(ChimeraMCPServer.from_env(name="chimera-tls-test"))
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=0,  # OS-assigned free port
        log_level="error",
        access_log=False,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started, "uvicorn failed to start with TLS"
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"https://127.0.0.1:{port}"

        async with httpx.AsyncClient(verify=False) as client:
            # TLS handshake + health.
            resp = await client.get(f"{base}/health")
            assert resp.status_code == 200
            assert "chimera ok" in resp.text
            # Bearer auth still gates /mcp over TLS.
            resp = await client.post(f"{base}/mcp", json={})
            assert resp.status_code == 401
            resp = await client.post(
                f"{base}/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"Authorization": "Bearer tls-drill-token"},
            )
            assert resp.status_code != 401
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
