"""Tests for subprocess environment hygiene (2026-06 security hardening).

Secrets (API keys, peer tokens, cloud credentials) must never be handed to
the child processes spawned by the shell and code_exec tools, while the
operational toolchain vars (PATH/HOME/GIT_*/UV_*/LANG…) must pass through.
"""

from __future__ import annotations

from chimera.tools.sandbox_env import is_secret_env_name, sanitized_subprocess_env


def test_strips_well_known_provider_keys():
    base = {
        "ANTHROPIC_API_KEY": "sk-ant-secret",
        "OPENROUTER_API_KEY": "sk-or-secret",
        "OPENAI_API_KEY": "sk-secret",
        "EXA_API_KEY": "exa-secret",
        "CHIMERA_PEER_TOKEN": "bearer-secret",
        "CHIMERA_PEER_TOKENS": '{"peer":"tok"}',
        "GITHUB_TOKEN": "ghp_secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "DB_PASSWORD": "hunter2",
    }
    out = sanitized_subprocess_env(base)
    assert out == {}, f"all secret-named vars should be stripped, got {out}"


def test_keeps_operational_toolchain_vars():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/agent",
        "USER": "agent",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "TZ": "UTC",
        "TMPDIR": "/tmp",
        "VIRTUAL_ENV": "/repo/.venv",
        "UV_CACHE_DIR": "/repo/.uv",
        "GIT_AUTHOR_NAME": "Chimera",
        "CHIMERA_MIND_DIR": "/repo/mind",
        "CHIMERA_STATE_DIR": "/repo/state",
        "CHIMERA_ENGINES_ENABLED": "1",
    }
    out = sanitized_subprocess_env(base)
    assert out == base, "operational vars must survive untouched"


def test_secret_detection_is_case_insensitive():
    assert is_secret_env_name("anthropic_api_key")
    assert is_secret_env_name("My_Secret_Thing")
    assert is_secret_env_name("SERVICE_TOKEN")
    assert not is_secret_env_name("PATH")
    assert not is_secret_env_name("CHIMERA_MIND_DIR")


def test_peer_token_specifically_stripped():
    # The bearer tokens that authenticate this agent to peers must never
    # reach a child process the model can read.
    assert is_secret_env_name("CHIMERA_PEER_TOKEN")
    assert is_secret_env_name("CHIMERA_PEER_TOKENS")


def test_default_reads_process_environ(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    out = sanitized_subprocess_env()
    assert "ANTHROPIC_API_KEY" not in out
    assert out.get("PATH") == "/usr/bin"
