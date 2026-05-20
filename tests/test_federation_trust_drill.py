"""v4.26 — peer trust-gating federation drill integration test.

Spawns the same `uv run chimera serve` subprocess as v4.20 but drives
both paths through PeerAwareDispatcher: default (T0 → REFUSE) and
seeded healthy (T2 → ALLOW). Verifies the peer_trust_journal captures
both decisions.

Skipped automatically if ``uv`` isn't on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chimera.scenarios import run_federation_trust_drill


pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def isolated_journals(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "CHIMERA_PROTOCOL_JOURNAL_DIR", str(tmp_path / "protocol_journal")
    )
    monkeypatch.setenv(
        "CHIMERA_PEER_TRUST_JOURNAL_DIR", str(tmp_path / "trust_journal")
    )


def _have_uv() -> bool:
    return shutil.which("uv") is not None


def test_trust_drill_walks_refuse_degrade_allow(tmp_path: Path):
    if not _have_uv():
        pytest.skip("uv not on PATH; cannot spawn `uv run chimera serve`")

    result = run_federation_trust_drill(tmp_path / "peer")

    assert result.ok, f"drill failed: {result.failures}"
    # Default peer state → T0 LOCKED → REFUSE.
    assert result.locked_decision == "REFUSE"
    assert result.locked_reason is not None
    assert "T0" in result.locked_reason
    # v4.28: T1 → DEGRADE (above lockdown, below min_trust_tier_for_allow).
    assert result.degraded_decision == "DEGRADE"
    assert result.degraded_reason is not None
    assert "T1" in result.degraded_reason
    # DEGRADE still dispatches → witness signal present.
    assert "research_target" in result.degraded_call_text
    # Seeded T2 trust_state.json → ALLOW.
    assert result.healthy_decision == "ALLOW"
    # All three decisions captured in the per-peer trust journal.
    assert result.journal_records >= 3
