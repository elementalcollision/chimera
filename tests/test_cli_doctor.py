"""CLI-level integration tests for `chimera doctor` (v4.98+).

Calls the CLI via subprocess, following the same pattern as
tests/test_cli_trust.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_doctor(*args: str, state_dir: Path, mind_dir: Path | None = None) -> tuple[int, str, str]:
    # PATH must include the directory containing `uv` so the v4.119
    # `_check_uv_installed` doctor check (PR #17) does not return "error"
    # and force a non-zero CLI exit. Without this, rc==0 assertions below
    # fail on environments where uv is not in /usr/bin or /bin.
    import shutil as _shutil
    uv_path = _shutil.which("uv")
    extra_dirs = [str(Path(uv_path).parent)] if uv_path else []
    path_parts = ["/usr/bin", "/bin", *extra_dirs]
    env = {
        "PATH": ":".join(path_parts),
        "CHIMERA_STATE_DIR": str(state_dir),
        "CHIMERA_MIND_DIR": str(mind_dir or state_dir / "mind"),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "doctor", *args],
        env=env,
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout: str) -> str:
    """When --fix is combined with --json the fix line prefixes stdout;
    find the JSON object and return it."""
    idx = stdout.find("{")
    if idx == -1:
        return stdout
    return stdout[idx:]


def test_doctor_json_outputs_valid_json(tmp_path: Path) -> None:
    """--json output must parse as JSON and contain the expected keys."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    mind = tmp_path / "mind"
    mind.mkdir(parents=True, exist_ok=True)

    rc, out, err = _run_doctor("--json", state_dir=state, mind_dir=mind)
    combined = out + err
    assert rc == 0, combined

    payload = json.loads(out)
    assert payload["command"] == "doctor"
    assert "checks" in payload
    assert isinstance(payload["checks"], list)
    assert len(payload["checks"]) > 0
    for check in payload["checks"]:
        assert "name" in check, check
        assert "status" in check, check
        assert "message" in check, check
        assert check["status"] in ("ok", "warn", "error"), check


def test_doctor_text_output_unchanged(tmp_path: Path) -> None:
    """Regression check: text output maintains expected structure.

    Each check line starts with a bracketed marker and a padded name,
    preserving the pre-change visual shape.
    """
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    mind = tmp_path / "mind"
    mind.mkdir(parents=True, exist_ok=True)

    rc, out, err = _run_doctor(state_dir=state, mind_dir=mind)
    combined = out + err
    assert rc == 0, combined

    lines = out.splitlines()
    assert len(lines) > 0
    # First line is the banner
    assert "chimera doctor:" in lines[0]
    # Every subsequent line is a check with a bracketed marker
    for line in lines[1:]:
        assert line.startswith("  ["), f"Unexpected line shape: {line!r}"
        assert line[3] in ("✓", "!", "✗"), f"Unexpected marker: {line!r}"
        assert len(line) > 10  # has name + message


def test_doctor_json_with_fix(tmp_path: Path) -> None:
    """--json --fix combination must run without error and emit valid JSON."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    mind = tmp_path / "mind"
    mind.mkdir(parents=True, exist_ok=True)

    rc, out, err = _run_doctor("--json", "--fix", state_dir=state, mind_dir=mind)
    combined = out + err
    assert rc == 0, combined

    # The fix line prefixes stdout; extract the JSON object
    payload = json.loads(_extract_json(out))
    assert payload["command"] == "doctor"
    assert "checks" in payload
    assert isinstance(payload["checks"], list)
    assert len(payload["checks"]) > 0
    for check in payload["checks"]:
        assert "name" in check
        assert "status" in check
        assert "message" in check
