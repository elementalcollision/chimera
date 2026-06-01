"""Coupled multi-file fault validation runner — plan (dryrun)."""
from __future__ import annotations
import os, subprocess
from pathlib import Path
_S = Path(__file__).resolve().parents[1] / "scripts" / "validation_coupled.sh"

def _dry():
    return subprocess.run(["bash", str(_S)], capture_output=True, text=True,
                          env=dict(os.environ, CAMPAIGN_DRYRUN="1")).stdout

def test_dryrun_coupled_two_file_fallback_off():
    out = _dry()
    assert "COUPLED inverse pair" in out
    assert "chimera/tempc.py + chimera/tempf.py" in out
    assert "fixing one file alone breaks the round-trip" in out
    assert "fallback = OFF" in out
