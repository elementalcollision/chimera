"""Inbound peer attestation — token → identity → trust tier.

Per ADR 0012 (v2.7). The HTTP server's bearer-auth middleware
resolves the incoming token to a peer name via :func:`load_token_map`,
then stores that peer name in :data:`current_peer` (a contextvar)
before invoking the next handler. The MCP ``call_tool`` handler reads
the contextvar to decide what trust context the inbound call runs at:

  - **Unknown token** → middleware already returned 401.
  - **Known token, peer name resolved, peer state visible in registry**:
    feed the registry entry through :class:`PeerTrustPolicy`. REFUSE
    → 403-like error response. DEGRADE → ``trust_tier="T1"``. ALLOW →
    ``trust_tier="T2"`` (peers don't get higher than our supervised
    tier without a stronger signal).
  - **Known token but no registry entry** → fall back to
    ``trust_tier="T1"`` (the v2.0 baseline).

Tokens are configured via the ``CHIMERA_PEER_TOKENS`` env var, a JSON
object mapping token → peer name:

.. code-block:: bash

    CHIMERA_PEER_TOKENS='{"abc123": "chimera-alpha", "def456": "chimera-beta"}'

Anonymous mode (``CHIMERA_PEER_TOKEN`` unset) is still supported for
local dev; in that case the contextvar stays unset and inbound calls
run at the v2.0 baseline ``trust_tier="T1"``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_ENV_TOKEN_MAP = "CHIMERA_PEER_TOKENS"


# Set by the HTTP middleware once the bearer is validated. Read by the
# MCP ``call_tool`` handler when constructing DispatchContext.
current_peer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chimera_current_peer", default=None
)


def load_token_map(raw: str | None = None) -> dict[str, str]:
    """Parse ``CHIMERA_PEER_TOKENS`` JSON into a token→peer-name dict.

    Returns ``{}`` for unset/malformed input. Logs a warning on parse error.
    """
    raw = raw if raw is not None else os.environ.get(_ENV_TOKEN_MAP, "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("%s is not valid JSON: %s", _ENV_TOKEN_MAP, exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must be a JSON object", _ENV_TOKEN_MAP)
        return {}
    out: dict[str, str] = {}
    for token, peer in parsed.items():
        if not isinstance(token, str) or not isinstance(peer, str):
            continue
        if not token or not peer:
            continue
        out[token] = peer
    return out


def resolve_peer_for_token(
    token: str, *, token_map: dict[str, str] | None = None
) -> str | None:
    """Look up which peer (by name) is presenting ``token``."""
    tm = token_map if token_map is not None else load_token_map()
    return tm.get(token)


def lookup_peer_state(peer_name: str) -> dict[str, Any] | None:
    """Pull a peer's last-known state from the peer registry.

    Returns a dict shaped like the ``chimera-kfm-state`` payload so the
    same :class:`PeerTrustPolicy` can consume it. Missing entries → None.
    """
    from ..a2a import list_peers

    for entry in list_peers():
        if entry.agent_id == peer_name:
            return {
                # The registry doesn't carry KFM/drift; assume STABLE for
                # known-registered peers. v2.x can enrich by having peers
                # write their kfm snapshot into the registry alongside identity.
                "plan_kfm_state": "STABLE",
                "trust_tier_int": 2,
                "last_drift_score": 0.0,
                "agent_id": entry.agent_id,
                "version": entry.version,
            }
    return None
