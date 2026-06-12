"""_httpx_verify — bool|str → httpx verify mapping (2026-06-12 migration).

httpx deprecated ``verify=<str>`` (a cert path); a path must now be an
``ssl.SSLContext``. This helper does the conversion so the federation drill
helpers keep accepting a CA path while staying deprecation-clean.
"""

from __future__ import annotations

import ssl

from chimera.scenarios.federation_drill import _httpx_verify


def test_bool_passes_through():
    assert _httpx_verify(True) is True
    assert _httpx_verify(False) is False


def test_str_path_becomes_ssl_context(tmp_path):
    import subprocess
    import shutil

    if shutil.which("openssl") is None:
        import pytest
        pytest.skip("openssl not available")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    ctx = _httpx_verify(str(cert))
    assert isinstance(ctx, ssl.SSLContext)
