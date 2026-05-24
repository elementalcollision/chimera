"""Synthetic tests for scripts/soak_lib.sh's soak_run_chimera_with_watchdog.

ADR 0120 — the watchdog must kill a hung subprocess after the idle
timeout. We exercise it by overriding the `uv` command on PATH with a
shim that just `sleep`s, then assert the watchdog fires.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOAK_LIB = REPO_ROOT / "scripts" / "soak_lib.sh"


def _run(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S602
        ["bash", "-c", script],
        capture_output=True, text=True, timeout=60, env=env,
    )


def test_watchdog_fires_when_subprocess_hangs(tmp_path: Path) -> None:
    """Shim `uv` to a 60-second sleep; watchdog timeout = 3s; expect kill."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text("#!/usr/bin/env bash\nsleep 60\n")
    uv_shim.chmod(0o755)

    worktree = tmp_path / "wt"
    worktree.mkdir()
    log_file = tmp_path / "run.log"
    log_file.touch()

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"

    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        start=$(date +%s)
        soak_run_chimera_with_watchdog "{worktree}" "{log_file}" 3
        rc=$?
        end=$(date +%s)
        echo "RC=$rc"
        echo "ELAPSED=$((end - start))"
    """)
    t0 = time.time()
    result = _run(script, env=env)
    elapsed = time.time() - t0

    assert "RC=1" in result.stdout, f"expected watchdog return=1, got: {result.stdout!r}"
    assert elapsed < 30, f"watchdog took too long ({elapsed}s); expected ~5s"
    log_text = log_file.read_text()
    assert "watchdog" in log_text and "killed after 3s" in log_text


def test_watchdog_clean_exit_returns_zero(tmp_path: Path) -> None:
    """Shim `uv` to exit 0 immediately; watchdog should NOT fire."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text("#!/usr/bin/env bash\nexit 0\n")
    uv_shim.chmod(0o755)

    worktree = tmp_path / "wt"
    worktree.mkdir()
    log_file = tmp_path / "run.log"
    log_file.touch()

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"

    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        soak_run_chimera_with_watchdog "{worktree}" "{log_file}" 30
        echo "RC=$?"
    """)
    result = _run(script, env=env)
    assert "RC=0" in result.stdout, result.stdout
    assert "watchdog" not in log_file.read_text()


def test_watchdog_nonzero_exit_returns_zero(tmp_path: Path) -> None:
    """Non-zero exit (engine skip, gate denial) is normal — caller treats as success."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text("#!/usr/bin/env bash\nexit 7\n")
    uv_shim.chmod(0o755)

    worktree = tmp_path / "wt"
    worktree.mkdir()
    log_file = tmp_path / "run.log"
    log_file.touch()

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"

    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        soak_run_chimera_with_watchdog "{worktree}" "{log_file}" 30
        echo "RC=$?"
    """)
    result = _run(script, env=env)
    assert "RC=0" in result.stdout, result.stdout
    assert "non-zero exit (7)" in log_file.read_text()


def test_soak_lib_version_is_v3() -> None:
    result = _run(f"source {SOAK_LIB}; soak_lib_version")
    assert "v3" in result.stdout, result.stdout
    assert "watchdog" in result.stdout.lower()
