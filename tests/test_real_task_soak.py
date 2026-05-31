"""Real-task soak runner (B1 Chip 3): parameterization + INBOX (dryrun)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "real_task_soak.sh"


def _run(env_extra: dict, *, dryrun: bool = True):
    env = dict(os.environ)
    if dryrun:
        env["TASK_DRYRUN"] = "1"
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(_SCRIPT)], capture_output=True, text=True, env=env,
    )


def test_dryrun_builds_verify_gate_from_files_and_test():
    p = _run({
        "TASK_GOAL": "fix the flaky timeout in test_foo",
        "TASK_FILES": "chimera/foo.py tests/test_foo.py",
        "TASK_TEST": "tests/test_foo.py",
    })
    assert p.returncode == 0, p.stderr
    out = p.stdout
    assert "run id    = realtask-" in out
    # The gate is `chimera verify`, narrowed to each file + the test target.
    assert ("gate cmd  = uv run chimera verify --ruff chimera/foo.py "
            "--ruff tests/test_foo.py --test tests/test_foo.py") in out
    # INBOX carries the real task + the gate command + the locked scope.
    assert "fix the flaky timeout in test_foo" in out
    assert "chimera verify" in out
    assert "edit ONLY these files for the fix — chimera/foo.py tests/test_foo.py" in out


def test_dryrun_full_suite_when_no_test_target():
    p = _run({
        "TASK_GOAL": "bump ruff to 0.7",
        "TASK_FILES": "pyproject.toml",
    })
    assert p.returncode == 0, p.stderr
    assert "test      = <full suite>" in p.stdout
    # No --test flag in the gate when TASK_TEST is unset.
    assert "gate cmd  = uv run chimera verify --ruff pyproject.toml" in p.stdout
    assert "--test" not in p.stdout.split("gate cmd")[1].split("\n")[0]


def test_dryrun_autocommit_default_on_and_override():
    on = _run({"TASK_GOAL": "g", "TASK_FILES": "chimera/x.py"})
    assert "autocommit= 1" in on.stdout
    off = _run({
        "TASK_GOAL": "g", "TASK_FILES": "chimera/x.py",
        "CHIMERA_SOAK_AUTOCOMMIT": "0",
    })
    assert "autocommit= 0" in off.stdout


def test_missing_required_param_fails():
    p = _run({"TASK_FILES": "chimera/x.py"})  # no TASK_GOAL
    assert p.returncode != 0
    assert "TASK_GOAL" in p.stderr
