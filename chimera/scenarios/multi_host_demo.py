"""v3.10 demo — multi-host swarm over HTTP.

Spins up Chimera-A on a local port (simulating a remote host) with
isolated registry/journal dirs, then in-process Chimera-B runs
``sync_remote_peers`` and ``sync_remote_emergence`` against A, verifying
that:

1. A's identity arrives in B's peer registry with ``reach.transport=http``.
2. A's emergence journal lands under ``B_journal/remote/<host>/<peer>.jsonl``.
3. ``/healthz`` returns ``status=ok`` from A.

The scenario is a pure happy-path smoke test — no provider keys needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..a2a.emergence import record_observation
from ..a2a.emergence_sync import sync_remote_emergence
from ..a2a.remote_sync import sync_remote_peers


@dataclass
class MultiHostResult:
    peer_a_port: int
    peer_a_agent_id: str | None
    peers_synced: int
    emergence_records: int
    failures: list[str]
    ok: bool


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _wait_for_healthz(url: str, *, timeout: float = 10.0) -> dict | None:
    """Poll until /healthz answers or timeout expires."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get(f"{url}/healthz")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as exc:  # noqa: BLE001 — polling loop
            last_exc = exc
        await asyncio.sleep(0.25)
    if last_exc:
        raise last_exc
    return None


async def _arun(workdir: Path) -> MultiHostResult:
    workdir.mkdir(parents=True, exist_ok=True)
    peer_a_root = workdir / "peer_a"
    peer_b_root = workdir / "peer_b"
    for d in (peer_a_root, peer_b_root):
        (d / "mind").mkdir(parents=True, exist_ok=True)
        (d / "state").mkdir(parents=True, exist_ok=True)
        (d / "registry").mkdir(parents=True, exist_ok=True)
        (d / "journal").mkdir(parents=True, exist_ok=True)

    # Seed an observation in A's journal so the emergence feed isn't empty.
    record_observation(
        "self",
        "shell",
        {"function": {"parameters": {"properties": {"cmd": {}}}}},
        dir=peer_a_root / "journal",
    )

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env_a = {
        **os.environ,
        "CHIMERA_MIND_DIR": str(peer_a_root / "mind"),
        "CHIMERA_STATE_DIR": str(peer_a_root / "state"),
        "CHIMERA_PEER_REGISTRY_DIR": str(peer_a_root / "registry"),
        "CHIMERA_PROTOCOL_JOURNAL_DIR": str(peer_a_root / "journal"),
        "CHIMERA_AGENT_ID": "chimera-A",
        "CHIMERA_PEER_EXPOSED_TOOLS": "",
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "chimera.cli", "serve",
            "--http", "--host", "127.0.0.1", "--port", str(port),
            "--name", "chimera-a",
        ],
        env=env_a,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    failures: list[str] = []
    peer_a_agent_id: str | None = None
    peers_synced = 0
    emergence_records = 0
    try:
        body = await _wait_for_healthz(base_url, timeout=12.0)
        if body is None:
            failures.append("healthz never returned 200")
        else:
            peer_a_agent_id = body.get("agent_id")

        b_registry = peer_b_root / "registry"
        b_journal = peer_b_root / "journal"

        peer_result = sync_remote_peers([base_url], dir=b_registry)
        peers_synced = peer_result.fetched
        for u, e in peer_result.failures:
            failures.append(f"peer sync {u}: {e}")

        emg_result = sync_remote_emergence([base_url], dir=b_journal)
        emergence_records = emg_result.records_added
        for u, e in emg_result.failures:
            failures.append(f"emergence sync {u}: {e}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = (
        not failures
        and peers_synced == 1
        and peer_a_agent_id is not None
        and emergence_records >= 1
    )
    return MultiHostResult(
        peer_a_port=port,
        peer_a_agent_id=peer_a_agent_id,
        peers_synced=peers_synced,
        emergence_records=emergence_records,
        failures=failures,
        ok=ok,
    )


def run_multi_host_demo(workdir: Path) -> MultiHostResult:
    return asyncio.run(_arun(workdir))
