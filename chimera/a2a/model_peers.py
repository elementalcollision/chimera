"""Model-backed peers — multi-model engagement chain (ADR 0174).

ADR 0167 (power-of-two peer selection) and ADR 0171 (fan-out budget) are
compose-safe but have never live-fired, for the same structural reason:
nothing in a single-agent deployment ever *engages multiple models at once*.
`select_peer` has no candidates (no peer federation exists), and the fan-out
trim has nothing to trim (one model emitting one tool call at a time).

This module closes that gap by registering the existing cross-vendor ladder
rungs as **peers**: each vendor becomes a peer named ``model-<vendor>`` that
exposes the standard peer surface —

- ``mcp-model-<vendor>-chimera-identity``  (advertises the ``consult`` capability)
- ``mcp-model-<vendor>-chimera-kfm-state`` (healthy, ALLOW-shaped state)
- ``mcp-model-<vendor>-consult``           (a REAL provider call to that vendor's rung)

Because these are ordinary registry tools, the whole existing A2A stack
applies unchanged: ``list_peer_chimeras`` discovers them,
``PeerTrustPolicy``/``PeerAwareDispatcher`` gate them, and ADR 0167's
``select_peer("consult")`` finally has a genuine candidate set to two-choice
over. And because several ``mcp-model-*-consult`` tools sit in the ACT
catalog together, a task that asks for multi-vendor consultation naturally
induces multi-``tool_use`` batches — the fan-out source ADR 0171 needs.

Default-OFF (``CHIMERA_MODEL_PEERS``): nothing registers and every path is
byte-identical until opted in. Synthetic peer state is intentionally
conservative-honest: these peers are *local* provider bindings, so their
kfm-state reports zero drift and a STABLE plan — there is no remote agent
whose drift could diverge; the trust gate still runs end-to-end.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Callable

from ..config import flag_enabled
from ..providers.tiers import (
    SONNET_LADDER,
    LadderRung,
    Provider as ProviderKind,
    rung_vendor,
)

if TYPE_CHECKING:
    import sqlite3

    from ..tools import ToolRegistry

logger = logging.getLogger(__name__)

#: The capability every model peer advertises.
CONSULT_CAPABILITY = "consult"

#: Peer-name prefix; ``model-deepseek``, ``model-minimax``, ...
PEER_PREFIX = "model-"

#: Default response budget for one consult call. Reasoning-optimized rungs
#: starve to empty output on tiny budgets (model-tier re-eval 2026-06-01),
#: so this is deliberately not minimal.
_DEFAULT_MAX_TOKENS = 1024


def model_peers_enabled() -> bool:
    """Honour ``CHIMERA_MODEL_PEERS`` (default: off, ADR 0174).

    Same parsing shape as ``peer_selection_enabled`` (ADR 0167).
    """
    return flag_enabled("CHIMERA_MODEL_PEERS")


def default_vendor_rungs(*, ladder: list[LadderRung] | None = None) -> dict[str, LadderRung]:
    """Cheapest rung per distinct vendor, in ladder (cheapest-first) order.

    The SONNET ladder is the deliberate cross-vendor spread (deepseek,
    minimax, z-ai, qwen, mistralai, google, anthropic), so it is the natural
    candidate pool. ``CHIMERA_MODEL_PEER_VENDORS`` (comma-separated vendor
    namespaces) restricts the set; unset keeps the three cheapest vendors so
    the default opt-in stays inexpensive.
    """
    rungs = ladder if ladder is not None else SONNET_LADDER
    by_vendor: dict[str, LadderRung] = {}
    for r in rungs:
        by_vendor.setdefault(rung_vendor(r), r)

    raw = os.environ.get("CHIMERA_MODEL_PEER_VENDORS", "").strip()
    if raw:
        wanted = [v.strip() for v in raw.split(",") if v.strip()]
        return {v: by_vendor[v] for v in wanted if v in by_vendor}
    # Default: the three cheapest distinct vendors.
    out: dict[str, LadderRung] = {}
    for v, r in by_vendor.items():
        out[v] = r
        if len(out) >= 3:
            break
    return out


def _model_id_for(rung: LadderRung) -> str:
    return (
        rung.config.model_id
        if rung.config.provider is ProviderKind.ANTHROPIC
        else rung.config.openrouter_model_id
    )


def peer_name_for_vendor(vendor: str) -> str:
    return f"{PEER_PREFIX}{vendor}"


def register_model_peers(
    registry: "ToolRegistry",
    providers: dict[ProviderKind, Any],
    *,
    db: "sqlite3.Connection | None" = None,
    cycle_fn: Callable[[], int] | None = None,
    vendor_rungs: dict[str, LadderRung] | None = None,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> list[str]:
    """Register every available vendor rung as a model-backed peer.

    A vendor is skipped (not an error) when its rung's provider kind has no
    live provider in ``providers``. Returns the registered peer names.
    ``db``/``cycle_fn`` meter each consult call into the ``api_calls`` ledger
    (caller ``model_peer:<vendor>``) so multi-model engagement stays visible
    to the existing cost telemetry.
    """
    chosen = vendor_rungs if vendor_rungs is not None else default_vendor_rungs()
    registered: list[str] = []

    for vendor, rung in chosen.items():
        provider = providers.get(rung.config.provider)
        if provider is None:
            logger.info(
                "model-peers: skipping vendor %r (no %s provider configured)",
                vendor, rung.config.provider.value,
            )
            continue
        peer = peer_name_for_vendor(vendor)
        model_id = _model_id_for(rung)
        _register_one(
            registry,
            peer=peer,
            vendor=vendor,
            model_id=model_id,
            provider=provider,
            db=db,
            cycle_fn=cycle_fn,
            max_tokens=max_tokens,
        )
        registered.append(peer)

    return registered


def _register_one(
    registry: "ToolRegistry",
    *,
    peer: str,
    vendor: str,
    model_id: str,
    provider: Any,
    db: "sqlite3.Connection | None",
    cycle_fn: Callable[[], int] | None,
    max_tokens: int,
) -> None:
    toolset = "model-peers"

    async def _identity(args: dict[str, Any], context: Any) -> str:
        return json.dumps({
            "name": peer,
            "kind": "model-peer",          # local provider binding, not a remote agent
            "vendor": vendor,
            "model_id": model_id,
            "capabilities": [CONSULT_CAPABILITY],
        })

    async def _kfm_state(args: dict[str, Any], context: Any) -> str:
        # Honest synthetic state: a local provider binding has no plan of
        # its own and no drift history. T5/STABLE/0.0 is ALLOW-shaped by
        # construction; the policy still evaluates it on every dispatch.
        return json.dumps({
            "cycle": 0,
            "trust_tier": "T5",
            "trust_tier_int": 5,
            "plan_kfm_state": "STABLE",
            "last_drift_score": 0.0,
        })

    async def _consult(args: dict[str, Any], context: Any) -> str:
        from ..providers import Message

        question = str(args.get("question", "")).strip()
        if not question:
            return "error: 'question' is required"
        response = await provider.complete_with_tools(
            messages=[Message.user(question)],
            model_id=model_id,
            tools=[],
            max_tokens=max_tokens,
        )
        if db is not None:
            try:
                from ..memory import record_api_call

                record_api_call(
                    db,
                    cycle=cycle_fn() if cycle_fn is not None else 0,
                    provider=getattr(provider, "name", "unknown"),
                    model_id=model_id,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    latency_ms=response.latency_ms or None,
                    finish_reason=response.stop_reason,
                    caller=f"model_peer:{vendor}",
                )
            except Exception:  # noqa: BLE001 — metering must never break consult
                logger.exception("model-peers: api_calls metering failed; continuing")
        text = (response.text or "").strip()
        return f"[{model_id}] {text}" if text else f"[{model_id}] (empty response)"

    def _schema(name: str, description: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": params,
            },
        }

    no_params = {"type": "object", "properties": {}, "required": []}
    registry.register(
        name=f"mcp-{peer}-chimera-identity",
        toolset=toolset,
        schema=_schema(
            f"mcp-{peer}-chimera-identity",
            f"Identity card for the {vendor} model peer ({model_id}).",
            no_params,
        ),
        handler=_identity,
        description=f"Identity for model peer {peer}",
        override=True,
    )
    registry.register(
        name=f"mcp-{peer}-chimera-kfm-state",
        toolset=toolset,
        schema=_schema(
            f"mcp-{peer}-chimera-kfm-state",
            f"KFM/trust state for the {vendor} model peer.",
            no_params,
        ),
        handler=_kfm_state,
        description=f"KFM state for model peer {peer}",
        override=True,
    )
    registry.register(
        name=f"mcp-{peer}-consult",
        toolset=toolset,
        schema=_schema(
            f"mcp-{peer}-consult",
            (
                f"Consult the {vendor} model ({model_id}) with a question and "
                "return its answer. Use several mcp-model-*-consult tools in "
                "ONE response batch to compare vendors in parallel."
            ),
            {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to put to this model.",
                    },
                },
                "required": ["question"],
            },
        ),
        handler=_consult,
        description=f"Consult model peer {peer}",
        override=True,
    )


async def consult_selected_peer(
    dispatcher: Any,
    question: str,
    *,
    capability: str = CONSULT_CAPABILITY,
) -> tuple[str, str] | None:
    """The ADR 0167 call chain: two-choice select a peer, then consult it.

    ``dispatcher`` is a :class:`PeerAwareDispatcher` (its ``select_peer``
    honours ``CHIMERA_PEER_SELECTION``; its ``dispatch`` runs the trust
    gate). Returns ``(peer_name, answer)`` or ``None`` when selection is
    disabled or no eligible peer exists.
    """
    peer = await dispatcher.select_peer(capability)
    if peer is None:
        return None
    answer = await dispatcher.dispatch(
        f"mcp-{peer}-consult", {"question": question}, None,
    )
    return peer, answer


__all__ = [
    "CONSULT_CAPABILITY",
    "PEER_PREFIX",
    "consult_selected_peer",
    "default_vendor_rungs",
    "model_peers_enabled",
    "peer_name_for_vendor",
    "register_model_peers",
]
