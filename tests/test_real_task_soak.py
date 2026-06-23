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


def test_foreign_submit_optional_args_are_set_u_safe():
    """The foreign-pr submit invocation expands its OPTIONAL arg arrays with the
    ${arr[@]+"${arr[@]}"} guard, never a bare "${arr[@]}".

    On bash 3.2 (macOS default) a bare "${arr[@]}" on an EMPTY array trips
    `set -u` with "unbound variable" — which silently aborted the submit subshell
    and skipped the foreign PR (2026-06-23 drift-monitor walk-base: _fpr_reg set,
    _fpr_beh/_fpr_prop empty). The guard expands an empty array to nothing. This
    is a static check because TASK_DRYRUN exits before the submit block and the
    only path that reaches it runs the full agent loop.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    for arr in ("_fpr_reg", "_fpr_beh", "_fpr_prop"):
        bare = f'"${{{arr}[@]}}"'             # "${_fpr_reg[@]}"
        guarded = f'${{{arr}[@]+{bare}}}'     # ${_fpr_reg[@]+"${_fpr_reg[@]}"}
        assert guarded in text, (
            f"{arr} missing the set -u-safe ${{arr[@]+...}} guard"
        )
        # The bare form is a substring of the guard, so the safe invariant is that
        # EVERY bare expansion is the inner part of a guard — never standalone.
        assert text.count(bare) == text.count(guarded), (
            f'{arr} has an UNGUARDED "${{{arr}[@]}}" — unbound-variable on bash 3.2'
        )


def test_real_task_soak_is_syntactically_valid():
    """`bash -n` parses the whole script (guards against edit typos)."""
    p = subprocess.run(
        ["bash", "-n", str(_SCRIPT)], capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stderr
