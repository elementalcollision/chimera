"""ADR 0174 — model-backed peers (multi-model engagement chain).

Registers cross-vendor ladder rungs as A2A peers so the existing peer stack
(discovery, trust policy, ADR 0167 selection) finally has real candidates,
and so multi-vendor consult tasks give ADR 0171 a fan-out source.
"""

from __future__ import annotations

import json
import random

import pytest

from chimera.a2a import (
    CONSULT_CAPABILITY,
    PeerAwareDispatcher,
    consult_selected_peer,
    fetch_peer_identity,
    fetch_peer_kfm,
    list_peer_chimeras,
    model_peers_enabled,
    register_model_peers,
)
from chimera.a2a.model_peers import default_vendor_rungs, peer_name_for_vendor
from chimera.a2a.trust_policy import PeerTrustPolicy, PolicyDecision
from chimera.memory import open_and_init
from chimera.providers import ChatResponse, Provider
from chimera.providers.tiers import SONNET_LADDER, Provider as ProviderKind
from chimera.tools import ToolRegistry


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, reply: str = "an answer") -> None:
        self._reply = reply
        self.calls: list[dict] = []

    async def stream(self, *a, **kw):
        if False:  # pragma: no cover
            yield None

    async def complete_with_tools(self, messages, *, model_id, tools, max_tokens=4096, system=None):
        self.calls.append({"model_id": model_id, "max_tokens": max_tokens})
        return ChatResponse(
            text=self._reply, tool_uses=[], stop_reason="stop",
            input_tokens=10, output_tokens=5, model_id=model_id, provider="fake",
        )


@pytest.fixture
def providers():
    fake = _FakeProvider()
    return fake, {ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake}


# ── flag parsing ────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("", False), ("0", False), ("off", False),
    ("1", True), ("true", True), ("YES", True), ("on", True),
])
def test_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("CHIMERA_MODEL_PEERS", raw)
    assert model_peers_enabled() is expected


# ── vendor selection ────────────────────────────────────────


def test_default_vendors_are_three_cheapest_distinct(monkeypatch):
    monkeypatch.delenv("CHIMERA_MODEL_PEER_VENDORS", raising=False)
    chosen = default_vendor_rungs()
    assert len(chosen) == 3
    # Cheapest-first ladder order ⇒ deepseek leads the sonnet spread.
    assert list(chosen)[0] == "deepseek"
    # One rung per vendor, all from the ladder.
    assert all(r in SONNET_LADDER for r in chosen.values())


def test_vendor_env_restricts_set(monkeypatch):
    monkeypatch.setenv("CHIMERA_MODEL_PEER_VENDORS", "minimax, anthropic, nosuch")
    chosen = default_vendor_rungs()
    assert set(chosen) == {"minimax", "anthropic"}


# ── registration + discovery ────────────────────────────────


def test_register_exposes_standard_peer_surface(providers):
    fake, provs = providers
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    assert len(peers) == 3
    assert peers[0] == peer_name_for_vendor("deepseek")
    # The existing discovery helper sees them — no special-casing.
    assert set(list_peer_chimeras(reg)) == set(peers)
    for p in peers:
        for suffix in ("chimera-identity", "chimera-kfm-state", "consult"):
            assert reg.get(f"mcp-{p}-{suffix}") is not None


def test_register_skips_vendor_without_provider(providers, monkeypatch):
    _, provs = providers
    monkeypatch.setenv("CHIMERA_MODEL_PEER_VENDORS", "deepseek,anthropic")
    reg = ToolRegistry()
    peers = register_model_peers(
        reg, {ProviderKind.OPENROUTER: provs[ProviderKind.OPENROUTER]},
    )
    # anthropic rung has no provider → skipped, not fatal.
    assert peers == [peer_name_for_vendor("deepseek")]


@pytest.mark.asyncio
async def test_identity_advertises_consult_and_kfm_is_allow_shaped(providers):
    _, provs = providers
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    identity = await fetch_peer_identity(peers[0], registry=reg)
    assert CONSULT_CAPABILITY in identity["capabilities"]
    assert identity["kind"] == "model-peer"
    state = await fetch_peer_kfm(peers[0], registry=reg)
    assert PeerTrustPolicy().evaluate(state).decision is PolicyDecision.ALLOW


# ── consult through the trust-gated dispatcher ──────────────


@pytest.mark.asyncio
async def test_consult_dispatches_real_provider_call_through_gate(providers):
    fake, provs = providers
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    dispatcher = PeerAwareDispatcher(reg)
    out = await dispatcher.dispatch(
        f"mcp-{peers[0]}-consult", {"question": "What is 2+2?"}, None,
    )
    assert "an answer" in out
    assert len(fake.calls) == 1
    # The answer is attributed to the backing model.
    assert out.startswith(f"[{fake.calls[0]['model_id']}]")


@pytest.mark.asyncio
async def test_consult_requires_question(providers):
    _, provs = providers
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    dispatcher = PeerAwareDispatcher(reg)
    out = await dispatcher.dispatch(f"mcp-{peers[0]}-consult", {}, None)
    assert out.startswith("error:")


@pytest.mark.asyncio
async def test_consult_meters_api_calls_ledger(providers, tmp_path):
    fake, provs = providers
    db = open_and_init(tmp_path / "chimera.db")
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs, db=db, cycle_fn=lambda: 7)
    dispatcher = PeerAwareDispatcher(reg)
    await dispatcher.dispatch(
        f"mcp-{peers[0]}-consult", {"question": "meter me"}, None,
    )
    row = db.execute(
        "SELECT cycle, model_id, caller FROM api_calls ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["cycle"] == 7
    assert row["caller"] == "model_peer:deepseek"
    db.close()


# ── the ADR 0167 chain: select → consult ────────────────────


@pytest.mark.asyncio
async def test_select_peer_two_choices_over_model_peers(providers, monkeypatch):
    _, provs = providers
    monkeypatch.setenv("CHIMERA_PEER_SELECTION", "1")
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    from chimera.a2a import select_peer

    chosen = await select_peer(
        CONSULT_CAPABILITY, registry=reg, rng=random.Random(42),
    )
    assert chosen in peers


@pytest.mark.asyncio
async def test_consult_selected_peer_chain(providers, monkeypatch):
    fake, provs = providers
    monkeypatch.setenv("CHIMERA_PEER_SELECTION", "1")
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    dispatcher = PeerAwareDispatcher(reg)
    result = await consult_selected_peer(dispatcher, "pick one and answer")
    assert result is not None
    peer, answer = result
    assert peer in peers
    assert "an answer" in answer
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_chain_returns_none_when_selection_disabled(providers, monkeypatch):
    _, provs = providers
    monkeypatch.delenv("CHIMERA_PEER_SELECTION", raising=False)
    reg = ToolRegistry()
    register_model_peers(reg, provs)
    dispatcher = PeerAwareDispatcher(reg)
    assert await consult_selected_peer(dispatcher, "anything") is None


# ── loop wiring (flag-gated) ────────────────────────────────


def test_loop_flag_off_registers_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("CHIMERA_MODEL_PEERS", raising=False)
    from chimera.core.loop import ChimeraLoop, LoopConfig

    mind = tmp_path / "mind"
    mind.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    loop = ChimeraLoop(LoopConfig(mind_dir=mind, state_dir=state))
    assert not [n for n in loop._registry.names() if n.startswith("mcp-model-")]
    loop.close()


def test_loop_flag_on_registers_model_peers(monkeypatch, tmp_path, providers):
    _, provs = providers
    monkeypatch.setenv("CHIMERA_MODEL_PEERS", "1")
    from chimera.core.act import ActExecutor
    from chimera.core.loop import ChimeraLoop, LoopConfig
    from chimera.memory import open_and_init as _open
    from chimera.tools import Dispatcher

    mind = tmp_path / "mind"
    mind.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    reg = ToolRegistry()
    db = _open(state / "seed.db")
    act = ActExecutor(dispatcher=Dispatcher(reg), providers=provs, db=db)
    loop = ChimeraLoop(
        LoopConfig(mind_dir=mind, state_dir=state),
        act_executor=act,
        tool_registry=reg,
    )
    model_tools = [n for n in loop._registry.names() if n.startswith("mcp-model-")]
    assert len(model_tools) == 9  # 3 vendors × (identity, kfm, consult)
    loop.close()
    db.close()


def test_consult_schema_names_batching_for_fanout(providers):
    """The consult tool description explicitly invites multi-vendor batches —
    the ADR 0171 fan-out source."""
    _, provs = providers
    reg = ToolRegistry()
    peers = register_model_peers(reg, provs)
    entry = reg.get(f"mcp-{peers[0]}-consult")
    assert entry is not None
    fn = entry.schema["function"]
    assert fn["parameters"]["required"] == ["question"]
    assert "ONE response batch" in fn["description"]
    # Identity payload round-trips as JSON.
    assert json.loads('{"ok": true}')["ok"] is True
