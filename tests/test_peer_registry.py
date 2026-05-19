"""Tests for the v2.2 peer registry."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chimera.a2a import AgentIdentity
from chimera.a2a.registry import (
    REGISTRY_SCHEMA_VERSION,
    PeerEntry,
    _safe_filename,
    forget,
    list_peers,
    register,
    registry_dir,
    sweep_stale,
)


@pytest.fixture
def reg_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "peers"
    d.mkdir()
    monkeypatch.setenv("CHIMERA_PEER_REGISTRY_DIR", str(d))
    return d


def test_registry_dir_honours_env(reg_dir):
    assert registry_dir().resolve() == reg_dir.resolve()


def test_safe_filename_replaces_bad_chars():
    assert _safe_filename("a/b c:d") == "a_b_c_d.json"
    assert _safe_filename("chimera-host-abc.123") == "chimera-host-abc.123.json"


def test_register_writes_entry(reg_dir):
    ident = AgentIdentity(agent_id="chimera-test-a")
    path = register(ident)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION
    assert data["agent_id"] == "chimera-test-a"
    assert data["pid"] == os.getpid()
    assert "shell" in data["capabilities"]


def test_list_peers_returns_what_register_writes(reg_dir):
    register(AgentIdentity(agent_id="chimera-alpha"))
    register(AgentIdentity(agent_id="chimera-beta"))
    entries = list_peers()
    ids = {e.agent_id for e in entries}
    assert ids == {"chimera-alpha", "chimera-beta"}


def test_forget_removes_entry(reg_dir):
    register(AgentIdentity(agent_id="chimera-ghost"))
    assert forget("chimera-ghost") is True
    assert list_peers() == []
    assert forget("chimera-ghost") is False  # idempotent


def test_list_peers_skips_malformed_files(reg_dir):
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "bad.json").write_text("{not json")
    (reg_dir / "missing-agent.json").write_text(json.dumps({"version": "1"}))
    register(AgentIdentity(agent_id="chimera-good"))
    entries = list_peers()
    assert [e.agent_id for e in entries] == ["chimera-good"]


def test_sweep_stale_removes_dead_local_entries(reg_dir, monkeypatch):
    import chimera.a2a.registry as mod

    monkeypatch.setattr(mod.socket, "gethostname", lambda: "localhost-test")
    # Live entry — our own pid.
    register(AgentIdentity(agent_id="chimera-alive"))
    # Dead entry — pid=1 may exist; use a clearly dead pid via patch.
    dead_path = reg_dir / "chimera-dead.json"
    dead_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_id": "chimera-dead",
                "version": "2.2.0",
                "capabilities": [],
                "pid": 9999999,  # almost certainly dead
                "host": "localhost-test",
                "reach": {"transport": "stdio", "command": ["chimera", "serve"]},
                "registered_at": "2026-05-19T00:00:00+00:00",
            }
        )
    )
    n = sweep_stale()
    assert n >= 1
    ids = {e.agent_id for e in list_peers()}
    assert "chimera-dead" not in ids
    assert "chimera-alive" in ids


def test_sweep_stale_ignores_remote_host_entries(reg_dir, monkeypatch):
    import chimera.a2a.registry as mod

    monkeypatch.setattr(mod.socket, "gethostname", lambda: "host-A")
    # Entry pretending to come from a different host.
    (reg_dir / "chimera-remote.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_id": "chimera-remote",
                "version": "2.2.0",
                "capabilities": [],
                "pid": 9999999,
                "host": "host-B",
                "reach": {"transport": "stdio", "command": ["chimera", "serve"]},
                "registered_at": "2026-05-19T00:00:00+00:00",
            }
        )
    )
    n = sweep_stale()
    assert n == 0


def test_peer_entry_roundtrip(reg_dir):
    ident = AgentIdentity(agent_id="chimera-roundtrip")
    path = register(ident)
    data = json.loads(path.read_text())
    entry = PeerEntry.from_dict(data)
    assert entry.agent_id == "chimera-roundtrip"
    assert entry.schema_version == 1
    assert entry.reach["transport"] == "stdio"
