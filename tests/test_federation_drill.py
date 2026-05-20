"""v4.20 — peer federation drill integration test.

Spawns a real `uv run chimera serve` subprocess and exercises the
identity handshake, KFM-state fetch, peer shell dispatch, and
protocol-journal observation recording end-to-end.

Marked ``slow`` because it spins up a subprocess via ``uv`` which can
take several seconds on a cold cache. Skipped automatically if ``uv``
isn't on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chimera.scenarios import run_federation_drill


pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def isolated_protocol_journal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "CHIMERA_PROTOCOL_JOURNAL_DIR", str(tmp_path / "protocol_journal")
    )


def _have_uv() -> bool:
    return shutil.which("uv") is not None


def test_federation_drill_round_trip(tmp_path: Path):
    if not _have_uv():
        pytest.skip("uv not on PATH; cannot spawn `uv run chimera serve`")

    result = run_federation_drill(tmp_path / "peer")

    assert result.ok, f"drill failed: {result.failures}"
    # Identity handshake worked and peer self-attests as chimera.
    assert result.identity is not None
    assert result.identity.get("role") == "chimera"
    assert result.identity.get("agent_id")
    # KFM-state fetch returned a plausible payload.
    assert result.kfm is not None
    assert "cycle" in result.kfm
    # Witness signal: the artifact we wrote is six lines long.
    assert result.witness_lines == 6
    # Protocol journal captured at least the identity + kfm + shell tools.
    assert result.observations_written >= 3
    assert result.journal_entries_after >= result.observations_written
    # Discovered the exposed tool set we expected.
    expected = {
        "mcp-chimera-a-chimera-identity",
        "mcp-chimera-a-chimera-kfm-state",
        "mcp-chimera-a-shell",
    }
    assert expected.issubset(set(result.discovered_tools))
