"""v4.20 / v4.26 — Peer federation drill.

Exercises the v2.x/v3.x peer-protocol code in anger:

  1. Chimera-B (this process) spawns Chimera-A via ``chimera serve``.
  2. Identity handshake (v2.1):  ``mcp-chimera-a-chimera-identity``.
  3. KFM-state fetch (v2.3):     ``mcp-chimera-a-chimera-kfm-state``.
  4. Witness call (v2.x shell):  B writes a research artifact into
     A's mind dir, then asks A's shell tool to compute a witness
     signal (line count via ``wc -l``).
  5. Protocol-journal observation recording (v2.9): every ``mcp-A-*``
     tool currently in the registry is appended to A's per-peer JSONL.

The drill returns a structured result so a test or the CLI can assert
each step succeeded. No model API keys required — this is the
protocol-level integration test we never had.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..a2a import (
    fetch_peer_identity,
    fetch_peer_kfm,
)
from ..a2a.emergence import (
    journal_dir as protocol_journal_dir,
    list_for_peer,
    record_observations_from_registry,
)
from ..tools import (
    DispatchContext,
    Dispatcher,
    MCPServerConfig,
    ToolRegistry,
    register_mcp_servers,
)


_PEER_NAME = "chimera-a"
_RESEARCH_FILENAME = "research_target.md"
_RESEARCH_CONTENT = (
    "# Research artifact\n"
    "\n"
    "Topic: parallel tool dispatch in agent loops.\n"
    "Finding-1: serial dispatch wastes O(sum) wall-clock.\n"
    "Finding-2: asyncio.gather collapses it to O(max).\n"
    "Finding-3: dispatcher policy still runs per-call.\n"
)


@dataclass
class FederationDrillResult:
    discovered_tools: list[str] = field(default_factory=list)
    identity: dict | None = None
    kfm: dict | None = None
    witness_lines: int | None = None
    witness_output: str = ""
    observations_written: int = 0
    journal_entries_after: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and self.witness_lines is not None


async def _arun(
    peer_root: Path,
    *,
    research_lines: int = 0,
) -> FederationDrillResult:
    """Asynchronously execute the drill.

    ``research_lines`` is overridden internally to match what we actually
    write — kept as a parameter for callers who want to seed alternate
    content via env in the future.
    """
    result = FederationDrillResult()

    peer_mind = peer_root / "mind"
    peer_state = peer_root / "state"
    peer_mind.mkdir(parents=True, exist_ok=True)
    peer_state.mkdir(parents=True, exist_ok=True)

    # (4) Pre-seed the research artifact in A's mind dir. A's shell tool
    # will read it via ``wc -l``.
    artifact_path = peer_mind / _RESEARCH_FILENAME
    artifact_path.write_text(_RESEARCH_CONTENT, encoding="utf-8")
    expected_lines = _RESEARCH_CONTENT.count("\n")

    # (1) Spawn Chimera-A as a subprocess with shell exposed.
    cfg = {
        _PEER_NAME: MCPServerConfig(
            name=_PEER_NAME,
            command="uv",
            args=("run", "chimera", "serve"),
            env={
                "CHIMERA_PEER_EXPOSED_TOOLS": "shell",
                "CHIMERA_MIND_DIR": str(peer_mind),
                "CHIMERA_STATE_DIR": str(peer_state),
                "PATH": os.environ.get("PATH", ""),
            },
        )
    }
    reg = ToolRegistry()
    await register_mcp_servers(cfg, reg)
    result.discovered_tools = sorted(reg.names())

    # (2) Identity handshake.
    try:
        result.identity = await fetch_peer_identity(_PEER_NAME, registry=reg)
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"identity handshake failed: {exc}")

    if not (result.identity and result.identity.get("role") == "chimera"):
        result.failures.append("peer did not self-attest as role=chimera")

    # (3) KFM state fetch.
    try:
        result.kfm = await fetch_peer_kfm(_PEER_NAME, registry=reg)
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"kfm fetch failed: {exc}")

    # (4) Witness call: ask A's shell to line-count the research file.
    # A's shell's default cwd is the parent of mind/state (per L-2), so
    # we address the file as ``mind/<filename>`` rather than bare.
    dispatcher = Dispatcher(reg)
    artifact_relpath = f"mind/{_RESEARCH_FILENAME}"
    try:
        raw = await dispatcher.dispatch(
            f"mcp-{_PEER_NAME}-shell",
            {"argv": ["wc", "-l", artifact_relpath]},
            DispatchContext(),
        )
        result.witness_output = raw
        # ``wc -l`` output looks like "       5 research_target.md" then
        # the harness appends "[exit=0]" markers. Parse defensively.
        for line in raw.splitlines():
            line = line.strip()
            if line and line[:1].isdigit() and "research_target" in line:
                head = line.split()[0]
                try:
                    result.witness_lines = int(head)
                    break
                except ValueError:
                    continue
        if result.witness_lines is None:
            result.failures.append(
                f"could not parse line count from peer shell output: {raw!r}"
            )
        elif result.witness_lines != expected_lines:
            result.failures.append(
                f"witness mismatch: expected {expected_lines} lines, "
                f"peer reported {result.witness_lines}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"witness dispatch failed: {exc}")

    # (5) Record observations into B's protocol journal.
    try:
        records = record_observations_from_registry(_PEER_NAME, reg)
        result.observations_written = len(records)
        result.journal_entries_after = len(list_for_peer(_PEER_NAME))
        if result.observations_written == 0:
            result.failures.append(
                "expected ≥1 protocol-journal observation, got 0"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"observation record failed: {exc}")

    return result


def run_federation_drill(peer_root: Path) -> FederationDrillResult:
    return asyncio.run(_arun(peer_root))


def main() -> int:  # pragma: no cover — convenience for ad-hoc runs
    import tempfile

    with tempfile.TemporaryDirectory(prefix="chimera-fed-drill-") as td:
        # Isolate B's protocol journal under the same temp root.
        os.environ.setdefault(
            "CHIMERA_PROTOCOL_JOURNAL_DIR", str(Path(td) / "protocol_journal")
        )
        result = run_federation_drill(Path(td) / "peer")
        print(f"discovered_tools: {result.discovered_tools}")
        print(f"identity.role: {(result.identity or {}).get('role')}")
        print(f"kfm.cycle: {(result.kfm or {}).get('cycle')}")
        print(f"witness_lines: {result.witness_lines}")
        print(f"observations_written: {result.observations_written}")
        print(f"journal_dir: {protocol_journal_dir()}")
        if result.failures:
            print("FAILURES:")
            for f in result.failures:
                print(f"  - {f}")
        print(f"ok: {result.ok}")
        return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# ── v4.26: trust-gating variant ─────────────────────────────


@dataclass
class FederationTrustDrillResult:
    discovered_tools: list[str] = field(default_factory=list)
    locked_decision: str | None = None
    locked_reason: str | None = None
    locked_refused: bool = False
    degraded_decision: str | None = None
    degraded_reason: str | None = None
    degraded_call_text: str = ""
    healthy_decision: str | None = None
    healthy_reason: str | None = None
    healthy_call_text: str = ""
    journal_records: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.failures
            and self.locked_refused
            and self.degraded_decision == "DEGRADE"
            and self.healthy_decision == "ALLOW"
        )


async def _arun_trust_drill(peer_root: Path) -> FederationTrustDrillResult:
    """Drive both REFUSE and ALLOW paths through PeerAwareDispatcher.

    Two sub-runs against the same peer root so we exercise the gate
    under both default (T0 locked) and seeded-healthy (T2) state.
    Each sub-run uses its own ToolRegistry + isolated journal dir.
    """
    import json as _json

    from ..a2a import PeerAwareDispatcher, PeerCallRefused

    result = FederationTrustDrillResult()

    peer_mind = peer_root / "mind"
    peer_state = peer_root / "state"
    peer_mind.mkdir(parents=True, exist_ok=True)
    peer_state.mkdir(parents=True, exist_ok=True)
    (peer_mind / _RESEARCH_FILENAME).write_text(_RESEARCH_CONTENT, encoding="utf-8")

    base_env = {
        "CHIMERA_PEER_EXPOSED_TOOLS": "shell",
        "CHIMERA_MIND_DIR": str(peer_mind),
        "CHIMERA_STATE_DIR": str(peer_state),
        "PATH": os.environ.get("PATH", ""),
    }

    from ..a2a.peer_trust_journal import list_decisions as _list_decisions

    async def _one_run(*, tier: int) -> tuple[str | None, str | None, str]:
        """Spawn the peer, run one PeerAwareDispatcher call, return
        (decision, reason, call_text). Decision is read from the trust
        journal so we can distinguish ALLOW from DEGRADE — both succeed."""
        # Wipe + reseed the peer's trust state file BEFORE booting.
        # tier=0 → default (no file, peer reports T0); tier=N (N>=1) → write file.
        ts_path = peer_state / "trust_state.json"
        if tier >= 1:
            ts_path.write_text(
                _json.dumps(
                    {
                        "current_tier": tier,
                        "tier_entered_at": "2026-01-01T00:00:00+00:00",
                        "last_readiness": 0.9,
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )
        else:
            if ts_path.exists():
                ts_path.unlink()

        cfg = {
            _PEER_NAME: MCPServerConfig(
                name=_PEER_NAME,
                command="uv",
                args=("run", "chimera", "serve"),
                env=dict(base_env),
            )
        }
        reg = ToolRegistry()
        await register_mcp_servers(cfg, reg)
        result.discovered_tools = sorted(reg.names())

        # Snapshot journal length before to identify the new entry.
        pre = len(_list_decisions(_PEER_NAME))

        dispatcher = PeerAwareDispatcher(reg)
        artifact_relpath = f"mind/{_RESEARCH_FILENAME}"
        call_text = ""
        threw_refused = False
        try:
            call_text = await dispatcher.dispatch(
                f"mcp-{_PEER_NAME}-shell",
                {"argv": ["wc", "-l", artifact_relpath]},
                DispatchContext(),
            )
        except PeerCallRefused:
            threw_refused = True

        # Read the new journal entries — last one is this dispatch's decision.
        post = _list_decisions(_PEER_NAME)
        new_entries = post[pre:]
        if not new_entries:
            # Dispatcher should have journaled. If it didn't, surface.
            return ("REFUSE" if threw_refused else "ALLOW"), None, call_text
        rec = new_entries[-1]
        return rec.decision, rec.reason, call_text

    # ── Sub-run 1: default (T0 → REFUSE) ─────────────────
    try:
        decision, reason, _ = await _one_run(tier=0)
        result.locked_decision = decision
        result.locked_reason = reason
        result.locked_refused = decision == "REFUSE"
        if not result.locked_refused:
            result.failures.append(
                f"expected REFUSE on default T0 peer, got {decision}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"locked sub-run failed: {exc}")

    # ── Sub-run 2: T1 → DEGRADE (v4.28) ──────────────────
    # The policy default min_trust_tier_for_allow is 2, so a T1 peer is
    # "above lockdown but below allow" → DEGRADE. Dispatch still
    # proceeds but with the local context downgraded to T1.
    try:
        decision, reason, text = await _one_run(tier=1)
        result.degraded_decision = decision
        result.degraded_reason = reason
        result.degraded_call_text = text
        if decision != "DEGRADE":
            result.failures.append(
                f"expected DEGRADE on T1 peer, got {decision}: {reason}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"degraded sub-run failed: {exc}")

    # ── Sub-run 3: healthy (T2 → ALLOW) ──────────────────
    try:
        decision, reason, text = await _one_run(tier=2)
        result.healthy_decision = decision
        result.healthy_reason = reason
        result.healthy_call_text = text
        if decision != "ALLOW":
            result.failures.append(
                f"expected ALLOW on healthy T2 peer, got {decision}: {reason}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"healthy sub-run failed: {exc}")

    # ── Journal verification ─────────────────────────────
    # PeerAwareDispatcher records every evaluate() outcome into the
    # peer_trust_journal; expect at least two rows (one per sub-run).
    try:
        from ..a2a.peer_trust_journal import list_decisions

        records = list_decisions(_PEER_NAME)
        result.journal_records = len(records)
        if result.journal_records < 3:
            result.failures.append(
                f"expected ≥3 peer_trust_journal entries, got {result.journal_records}"
            )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(f"journal read failed: {exc}")

    return result


def run_federation_trust_drill(peer_root: Path) -> FederationTrustDrillResult:
    return asyncio.run(_arun_trust_drill(peer_root))


# ── v4.29: HTTP transport variant ───────────────────────────


@dataclass
class FederationHttpDrillResult:
    discovered_tools: list[str] = field(default_factory=list)
    server_url: str = ""
    health_ok: bool = False
    auth_rejected_anonymous: bool = False
    identity: dict | None = None
    kfm: dict | None = None
    witness_lines: int | None = None
    witness_output: str = ""
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.failures
            and self.health_ok
            and self.auth_rejected_anonymous
            and self.witness_lines is not None
        )


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _generate_token() -> str:
    import secrets
    return "tok_" + secrets.token_hex(8)


async def _wait_for_health(url: str, *, timeout_s: float = 10.0) -> bool:
    """Poll /healthz until 200 or timeout."""
    import httpx
    deadline = asyncio.get_event_loop().time() + timeout_s
    health = url.rstrip("/") + "/healthz"
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(health)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    return False


async def _check_anonymous_rejected(url: str) -> bool:
    """A bearer-protected /mcp endpoint should 401 without a token."""
    import httpx
    mcp = url.rstrip("/") + "/mcp"
    async with httpx.AsyncClient(timeout=2.0) as client:
        try:
            r = await client.post(mcp, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        except httpx.HTTPError:
            return False
        return r.status_code in (401, 403)


async def _arun_http_drill(peer_root: Path) -> FederationHttpDrillResult:
    """Drive identity/KFM/witness over HTTP/SSE with bearer auth."""
    import subprocess

    result = FederationHttpDrillResult()

    peer_mind = peer_root / "mind"
    peer_state = peer_root / "state"
    peer_mind.mkdir(parents=True, exist_ok=True)
    peer_state.mkdir(parents=True, exist_ok=True)
    (peer_mind / _RESEARCH_FILENAME).write_text(_RESEARCH_CONTENT, encoding="utf-8")

    port = _find_free_port()
    token = _generate_token()
    url = f"http://127.0.0.1:{port}"
    result.server_url = url

    env = {
        **os.environ,
        "CHIMERA_PEER_TOKEN": token,
        "CHIMERA_PEER_EXPOSED_TOOLS": "shell",
        "CHIMERA_MIND_DIR": str(peer_mind),
        "CHIMERA_STATE_DIR": str(peer_state),
        "PATH": os.environ.get("PATH", ""),
    }

    proc = subprocess.Popen(
        [
            "uv", "run", "chimera", "serve",
            "--http", "--host", "127.0.0.1", "--port", str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # (1) Health check.
        result.health_ok = await _wait_for_health(url, timeout_s=15.0)
        if not result.health_ok:
            result.failures.append(f"server failed to come up at {url}")
            return result

        # (2) Bearer auth gates /mcp.
        result.auth_rejected_anonymous = await _check_anonymous_rejected(url)
        if not result.auth_rejected_anonymous:
            result.failures.append("anonymous /mcp request was not rejected")

        # (3) Register the HTTP MCP server in our registry.
        cfg = {
            _PEER_NAME: MCPServerConfig(
                name=_PEER_NAME,
                transport="http",
                url=url + "/mcp",
                token=token,
            )
        }
        reg = ToolRegistry()
        await register_mcp_servers(cfg, reg)
        result.discovered_tools = sorted(reg.names())

        # (4) Identity + KFM.
        try:
            result.identity = await fetch_peer_identity(_PEER_NAME, registry=reg)
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"identity over HTTP failed: {exc}")
        if not (result.identity and result.identity.get("role") == "chimera"):
            result.failures.append("HTTP peer did not self-attest as role=chimera")
        try:
            result.kfm = await fetch_peer_kfm(_PEER_NAME, registry=reg)
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"kfm over HTTP failed: {exc}")

        # (5) Witness call.
        dispatcher = Dispatcher(reg)
        artifact_relpath = f"mind/{_RESEARCH_FILENAME}"
        try:
            raw = await dispatcher.dispatch(
                f"mcp-{_PEER_NAME}-shell",
                {"argv": ["wc", "-l", artifact_relpath]},
                DispatchContext(),
            )
            result.witness_output = raw
            for line in raw.splitlines():
                line = line.strip()
                if line and line[:1].isdigit() and "research_target" in line:
                    try:
                        result.witness_lines = int(line.split()[0])
                        break
                    except ValueError:
                        continue
            if result.witness_lines is None:
                result.failures.append(
                    f"could not parse line count from HTTP peer: {raw!r}"
                )
        except Exception as exc:  # noqa: BLE001
            result.failures.append(f"HTTP witness dispatch failed: {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    return result


def run_federation_http_drill(peer_root: Path) -> FederationHttpDrillResult:
    return asyncio.run(_arun_http_drill(peer_root))
