"""Stateful fault validation runner — plan (dryrun). Live run is operator action."""
from __future__ import annotations
import os, subprocess
from pathlib import Path
_S = Path(__file__).resolve().parents[1] / "scripts" / "validation_stateful.sh"

def _dry():
    return subprocess.run(["bash", str(_S)], capture_output=True, text=True,
                          env=dict(os.environ, CAMPAIGN_DRYRUN="1"))

def test_dryrun_stateful_class_fallback_off():
    out = _dry().stdout
    assert "RunningStats accumulator" in out
    assert "self._sum = x" in out and "self._sum += x" in out
    assert "fallback = OFF" in out
    assert "BLIND on a stateful class" in out
