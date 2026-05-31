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


def test_soak_lib_version_is_v5() -> None:
    result = _run(f"source {SOAK_LIB}; soak_lib_version")
    assert "v5" in result.stdout, result.stdout
    assert "mind/*" in result.stdout


# ─────────────────────────────────────────────────────────────────────
# soak_phase2_deliverable_landed — mind/* auto-allow (ADR 0121, v4)
# ─────────────────────────────────────────────────────────────────────
#
# Across soaks v19–v25 the agent reliably co-staged journal updates
# (CHRONICLE, HEARTBEAT, INBOX, SESSION_LOG, research design docs)
# alongside the deliverable, even when the charter said "TWO files
# only". v4 of soak_lib treats every mind/* path as operational
# artifact and admits them into a charter-clean diff. The whitelist
# remains strict for everything else.


def _make_worktree_with_diff(
    tmp_path: Path, touched: list[str], commit_msg: str = "[agent] deliverable"
) -> Path:
    """Build a tiny git repo with `main` and a feature branch that
    touches `touched` files and lands one [agent]-prefixed commit.
    Returns the worktree path."""
    wt = tmp_path / "wt"
    wt.mkdir()
    sh = (
        f'cd "{wt}" && '
        'git init -q -b main && '
        'git config user.email a@b && git config user.name a && '
        'echo seed > seed.txt && git add seed.txt && '
        'git commit -q -m seed && '
        'git checkout -q -b feature'
    )
    subprocess.run(["bash", "-c", sh], check=True, capture_output=True)
    for rel in touched:
        target = wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("payload\n")
    files = " ".join(f'"{f}"' for f in touched)
    subprocess.run(
        [
            "bash",
            "-c",
            f'cd "{wt}" && git add {files} && git commit -q -m "{commit_msg}"',
        ],
        check=True,
        capture_output=True,
    )
    return wt


def _landed(wt: Path, whitelist: str, test_cmd: str = "true") -> int:
    script = textwrap.dedent(f"""
        source {SOAK_LIB}
        soak_phase2_deliverable_landed "{wt}" "{whitelist}" "{test_cmd}"
        echo "RC=$?"
    """)
    result = _run(script)
    for line in result.stdout.splitlines():
        if line.startswith("RC="):
            return int(line.split("=", 1)[1])
    raise AssertionError(f"no RC line in output: {result.stdout!r} / {result.stderr!r}")


@pytest.mark.parametrize(
    "journal_path",
    [
        "mind/CHRONICLE.md",
        "mind/HEARTBEAT.md",
        "mind/INBOX.md",
        "mind/SESSION_LOG.md",
        "mind/research/foo-design.md",
        "mind/research/foo-remediation.md",
    ],
)
def test_mind_paths_are_auto_allowed(tmp_path: Path, journal_path: str) -> None:
    """v4: every mind/* path is admitted into a charter-clean diff."""
    wt = _make_worktree_with_diff(tmp_path, ["chimera/core/act.py", journal_path])
    rc = _landed(wt, "chimera/core/act.py")
    assert rc == 0, f"{journal_path} should be auto-allowed under v4"


def test_non_whitelisted_source_still_blocks(tmp_path: Path) -> None:
    """The v4 expansion does NOT loosen enforcement outside mind/."""
    wt = _make_worktree_with_diff(
        tmp_path, ["chimera/core/act.py", "chimera/core/escalation.py"]
    )
    rc = _landed(wt, "chimera/core/act.py")
    assert rc == 1, "extra source file outside whitelist must still block"


def test_docs_outside_mind_still_blocks(tmp_path: Path) -> None:
    """docs/ is NOT in the mind/ tree; must still be enforced."""
    wt = _make_worktree_with_diff(
        tmp_path, ["chimera/core/act.py", "docs/adr/0117-foo.md"]
    )
    rc = _landed(wt, "chimera/core/act.py")
    assert rc == 1, "docs/* must not be auto-allowed"


def test_whitelisted_files_only_still_landed(tmp_path: Path) -> None:
    """Pure whitelist match (no mind/* path) still returns 0 — v3 behavior preserved."""
    wt = _make_worktree_with_diff(tmp_path, ["chimera/core/act.py"])
    rc = _landed(wt, "chimera/core/act.py")
    assert rc == 0
