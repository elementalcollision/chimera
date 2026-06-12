"""Remote federation drill — ADR 0167 + 0168 certification over real HTTP.

Spawns three independent `uv run chimera serve --http` subprocesses (distinct
CHIMERA_AGENT_ID / port / token / state dir), seeds each with a real
trust_state.json so the live kfm_tool reports a real tier, then exercises the
genuine peer stack over the HTTP MCP transport:

  - the real PeerTrustPolicy gate (alpha/beta T4 → ALLOW, gamma T0 → REFUSE);
  - ADR 0167 select_peer two-choice — spreads only over the ALLOW pool,
    never the REFUSEd peer (the anti-herding property, over real remote peers);
  - ADR 0168 connectivity gauge — the REFUSEd peer isolates.

Skipped without ``uv`` on PATH; marked ``slow``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chimera.scenarios import run_remote_federation_drill


pytestmark = pytest.mark.slow


def _have_uv() -> bool:
    return shutil.which("uv") is not None


def test_remote_federation_selection_and_gauge(tmp_path: Path):
    if not _have_uv():
        pytest.skip("uv not on PATH; cannot spawn `uv run chimera serve --http`")

    result = run_remote_federation_drill(tmp_path / "fed")

    assert result.ok, f"drill failed: {result.failures}"
    assert result.health_ok
    assert result.peers == ["alpha", "beta", "gamma"]

    # Real trust gate over HTTP: seeded tiers drive real decisions.
    assert sorted(result.allow_peers) == ["alpha", "beta"]
    assert result.refuse_peers == ["gamma"]

    # ADR 0167: selection only ever picked trust-eligible peers, and it
    # spread across both rather than herding onto one.
    assert result.selection_spread, "select_peer produced no picks"
    assert set(result.selection_spread).issubset({"alpha", "beta"})
    assert "gamma" not in result.selection_spread
    assert len(result.selection_spread) == 2, "selection herded onto a single peer"

    # ADR 0168: gauge over the real remote trust journal isolates the REFUSEd
    # peer. operator + alpha + beta connected (3), gamma isolated ⇒ 3/4.
    c = result.connectivity
    assert c is not None
    assert c["n_nodes"] == 4
    assert c["largest_component"] == 3
    assert abs(c["connectivity"] - 0.75) < 1e-9
    assert c["isolated_nodes"] == 1
