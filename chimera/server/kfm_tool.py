"""The always-exposed ``chimera-kfm-state`` tool.

Per ADR 0008 (v2.3): each Chimera advertises its current swarm-relevant
state to peers via a single read-only tool. Returns a JSON payload with
the current plan entity's KFM state, last drift composite, current
trust tier, and cycle number. No writes; no LLM call.

The schema is intentionally minimal at v2.3 — enough for a peer to
decide "this peer is healthy / deprecated / locked down". Richer
coordination (e.g., voting, leader election) lands later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..tools import DispatchContext, ToolRegistry


KFM_STATE_TOOL_NAME = "chimera-kfm-state"

KFM_STATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": KFM_STATE_TOOL_NAME,
        "description": (
            "Return this Chimera's current swarm-relevant state: plan KFM "
            "lifecycle state, cycle, trust tier, last drift composite score. "
            "Always available; ignores the CHIMERA_PEER_EXPOSED_TOOLS allow-list. "
            "Pure read; no side-effects."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def _read_kfm_snapshot() -> dict[str, Any]:
    """Read the current plan + trust + cycle without taking heavy locks."""
    from ..core import LoopConfig, load_heartbeat
    from ..memory import get_entity_by_name, open_and_init
    from ..trust import TrustManager

    cfg = LoopConfig.from_env()
    snapshot: dict[str, Any] = {
        "cycle": 0,
        "trust_tier": "T0",
        "trust_tier_int": 0,
        "plan_kfm_state": None,
        "plan_name": None,
        "last_drift_score": None,
    }

    # Heartbeat for cycle + trust mirror.
    hb_path = cfg.mind_dir / "HEARTBEAT.md"
    if hb_path.exists():
        state, _ = load_heartbeat(hb_path)
        snapshot["cycle"] = state.cycle
        snapshot["trust_tier"] = state.trust_tier
        snapshot["last_drift_score"] = state.last_drift_score

    # TrustManager for authoritative tier integer.
    try:
        tm = TrustManager(cfg.state_dir / "trust_state.json")
        snapshot["trust_tier_int"] = int(tm.tier)
        snapshot["trust_tier"] = tm.tier.name
    except Exception:
        pass

    # Plan entity from SQLite (if the DB exists).
    db_path = cfg.state_dir / "chimera.db"
    if db_path.exists():
        try:
            conn = open_and_init(db_path)
            try:
                plan = get_entity_by_name(conn, kind="plan", name="current")
                if plan is not None:
                    snapshot["plan_kfm_state"] = plan.kfm_state
                    snapshot["plan_name"] = plan.name
                    snapshot["plan_state_entered_at_cycle"] = plan.state_entered_at_cycle
            finally:
                conn.close()
        except Exception:
            pass

    return snapshot


async def _handler(args: dict, context: DispatchContext) -> str:
    return json.dumps(_read_kfm_snapshot(), sort_keys=True)


def register_kfm_state_tool(registry: ToolRegistry) -> None:
    """Idempotent: register the swarm-KFM tool."""
    registry.register(
        name=KFM_STATE_TOOL_NAME,
        toolset="peer",
        schema=KFM_STATE_SCHEMA,
        handler=_handler,
        description="Peer swarm-KFM state (always exposed).",
        override=True,
    )
