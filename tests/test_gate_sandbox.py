"""Tests for the gate sandbox (ADR 0186 B.4 M1).

The foreign (and, by the 2026-06-20 decision, self) gate runs ruff/pytest with
provider secrets stripped from its environment, so an untrusted ``verify_cmd``
can't read our keys. Two implementations must agree: the shell helper
``soak_gate_run`` (scripts/_soak_common.sh) for the bash gate paths, and
``_gate_subprocess_env`` (chimera/core/repo_verify.py) for the argv path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from chimera.core.repo_verify import _gate_subprocess_env
from chimera.tools.sandbox_env import _SECRET_NAME_PATTERNS

_COMMON = Path(__file__).resolve().parent.parent / "scripts" / "_soak_common.sh"


def _bash(snippet: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"source '{_COMMON}'\n{snippet}"],
        capture_output=True, text=True, env=env,
    )


def _env_with(**extra: str) -> dict:
    e = dict(os.environ)
    e.update(extra)
    return e


# ── sync guard: shell denylist ⊇ python patterns ────────────


def test_shell_denylist_covers_every_python_pattern():
    txt = _COMMON.read_text()
    for pat in _SECRET_NAME_PATTERNS:
        assert pat in txt, f"secret pattern {pat!r} missing from shell _SOAK_SECRET_RE"


# ── shell: soak_gate_run ────────────────────────────────────


def test_soak_gate_run_strips_secrets_keeps_operational(tmp_path):
    r = _bash(
        f"soak_gate_run '{tmp_path}' 'env'",
        env=_env_with(FAKE_API_KEY="sekret", MY_TOKEN="t", ZZ_SECRET="s",
                      CHIMERA_GATE_SANDBOX="1"),
    )
    assert r.returncode == 0
    assert "FAKE_API_KEY" not in r.stdout
    assert "MY_TOKEN" not in r.stdout
    assert "ZZ_SECRET" not in r.stdout
    assert "PATH=" in r.stdout  # operational var passes through


def test_soak_gate_run_strips_provider_branded_keys(tmp_path):
    r = _bash(
        f"soak_gate_run '{tmp_path}' 'env'",
        env=_env_with(ANTHROPIC_API_KEY="sk-a", OPENROUTER_API_KEY="sk-o"),
    )
    assert "ANTHROPIC_API_KEY" not in r.stdout
    assert "OPENROUTER_API_KEY" not in r.stdout


def test_soak_gate_run_runs_command_and_propagates_exit(tmp_path):
    assert _bash(f"soak_gate_run '{tmp_path}' 'exit 3'").returncode == 3
    ok = _bash(f"soak_gate_run '{tmp_path}' 'echo hello'")
    assert ok.returncode == 0 and "hello" in ok.stdout


def test_soak_gate_run_executes_in_dir(tmp_path):
    r = _bash(f"soak_gate_run '{tmp_path}' 'pwd'")
    assert str(tmp_path) in r.stdout


def test_soak_gate_run_killswitch_off_keeps_secrets(tmp_path):
    r = _bash(
        f"soak_gate_run '{tmp_path}' 'env'",
        env=_env_with(FAKE_API_KEY="sekret", CHIMERA_GATE_SANDBOX="0"),
    )
    assert "FAKE_API_KEY" in r.stdout  # kill-switch → original behaviour


# ── python: _gate_subprocess_env ────────────────────────────


def test_gate_env_strips_secrets_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_GATE_SANDBOX", raising=False)
    monkeypatch.setenv("FAKE_API_KEY", "x")
    env = _gate_subprocess_env()
    assert env is not None
    assert "FAKE_API_KEY" not in env
    assert "PATH" in env  # operational var retained


def test_gate_env_killswitch_off_returns_none(monkeypatch):
    monkeypatch.setenv("CHIMERA_GATE_SANDBOX", "0")
    assert _gate_subprocess_env() is None
