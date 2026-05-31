"""Deep validation campaign runner — plan/config (dryrun).

The live campaign launches n=3 real soaks (an explicit operator action); these
tests pin the dryrun plan so the manifest + caps + fallback posture are correct
before anything runs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validation_campaign.sh"


def _dryrun(env_extra=None):
    env = dict(os.environ, CAMPAIGN_DRYRUN="1")
    env.update(env_extra or {})
    return subprocess.run(["bash", str(_SCRIPT)], capture_output=True, text=True, env=env)


def test_dryrun_lists_three_runs_fallback_off():
    p = _dryrun()
    assert p.returncode == 0, p.stderr
    out = p.stdout
    assert "runs     = 3" in out
    assert "fallback = OFF" in out
    for rid in ("v1", "v2", "v3"):
        assert f"- {rid} " in out
    # the n=3 design: 2 faithful-fix + 1 regression-tempting
    assert out.count("faithful-fix") == 2
    assert "regression-tempting" in out


def test_dryrun_caps_are_meaningful_length():
    p = _dryrun()
    assert "phase1 $3.00" in p.stdout and "phase2 $1.50" in p.stdout
    assert "wall 2400s" in p.stdout


def test_dryrun_caps_overridable():
    p = _dryrun({"PHASE1_CAP_USD": "5.00", "MAX_WALL_SECONDS": "3600"})
    assert "phase1 $5.00" in p.stdout
    assert "wall 3600s" in p.stdout


def test_dryrun_targets_real_modules():
    out = _dryrun().stdout
    assert "chimera/numfmt.py" in out
    assert "chimera/seqstats.py" in out
    assert "chimera/strcase.py" in out
