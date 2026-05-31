"""Generic charter-build runner: parameterization + validation (dryrun)."""

from __future__ import annotations

import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "charter_build_soak.sh"


def _run(env_extra: dict, *, dryrun: bool = True):
    import os
    env = dict(os.environ)
    if dryrun:
        env["CHARTER_DRYRUN"] = "1"
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(_SCRIPT)], capture_output=True, text=True, env=env,
    )


def test_dryrun_derives_config_for_any_module():
    p = _run({
        "CHARTER_MODULE": "durparse",
        "CHARTER_TARGET": "chimera/durparse.py",
        "CHARTER_TEST": "tests/test_durparse.py",
        "CHARTER_GOAL": "parse a duration string",
    })
    assert p.returncode == 0, p.stderr
    out = p.stdout
    assert "run id    = charter-durparse-" in out
    assert "gate cmd  = uv run --extra dev pytest -q tests/test_durparse.py" in out
    # INBOX is templated with the module's real paths.
    assert "Create ONE new module `chimera/durparse.py`" in out
    assert "`tests/test_durparse.py`" in out
    assert "parse a duration string" in out


def test_dryrun_works_for_a_different_module():
    p = _run({
        "CHARTER_MODULE": "bytefmt",
        "CHARTER_TARGET": "chimera/bytefmt.py",
        "CHARTER_TEST": "tests/test_bytefmt.py",
    })
    assert p.returncode == 0, p.stderr
    assert "module    = bytefmt" in p.stdout
    assert "chimera/bytefmt.py" in p.stdout
    # Default goal when none supplied.
    assert "build chimera/bytefmt.py" in p.stdout


def test_missing_required_param_fails():
    # No CHARTER_MODULE → the `:?` guard aborts non-zero.
    p = _run({"CHARTER_TARGET": "chimera/x.py", "CHARTER_TEST": "tests/test_x.py"})
    assert p.returncode != 0
    assert "CHARTER_MODULE" in p.stderr


def test_autocommit_default_on():
    p = _run({
        "CHARTER_MODULE": "m", "CHARTER_TARGET": "chimera/m.py",
        "CHARTER_TEST": "tests/test_m.py",
    })
    assert "autocommit= 1" in p.stdout


def test_autocommit_override_off():
    p = _run({
        "CHARTER_MODULE": "m", "CHARTER_TARGET": "chimera/m.py",
        "CHARTER_TEST": "tests/test_m.py", "CHIMERA_SOAK_AUTOCOMMIT": "0",
    })
    assert "autocommit= 0" in p.stdout
