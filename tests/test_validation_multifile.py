"""Multi-file fault validation runner — plan (dryrun). The live run is an
explicit operator action; this pins the two-file/combined-test design."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_S = Path(__file__).resolve().parents[1] / "scripts" / "validation_multifile.sh"


def _dry():
    env = dict(os.environ, CAMPAIGN_DRYRUN="1")
    return subprocess.run(["bash", str(_S)], capture_output=True, text=True, env=env)


def test_dryrun_two_file_fix_fallback_off():
    p = _dry()
    assert p.returncode == 0, p.stderr
    out = p.stdout
    assert "chimera/numfmt.py + chimera/seqstats.py" in out
    assert "fallback = OFF" in out
    assert "combined contract" in out


def test_dryrun_faults_named():
    out = _dry().stdout
    assert "while value >= 1024" in out
    assert "if v > current" in out
