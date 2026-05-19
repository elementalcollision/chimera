"""PeerAwareDispatcher — wires :class:`PeerTrustPolicy` into the call path.

Per ADR 0010 (v2.5). Subclass of :class:`chimera.tools.Dispatcher`. On
each ``mcp-<peer>-<tool>`` call (other than identity/kfm-state), it:

  1. Looks up the peer's last-known state via :class:`PeerStateCache`.
  2. On cache miss, fetches via ``mcp-<peer>-chimera-kfm-state`` (which
     is allow-listed and always reachable, even on REFUSED peers).
  3. Runs :class:`PeerTrustPolicy` on the state.
  4. REFUSE → raise :class:`PeerCallRefused` (subclass of ToolDenied).
  5. DEGRADE → dispatch with ``DispatchContext(trust_tier="T1")``.
  6. ALLOW → dispatch with the caller's original context.

Non-peer tools (``shell``, ``code_exec``, dynamic skills, etc.) pass
through unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..tools import DispatchContext, Dispatcher, ToolDenied, ToolRegistry
from .trust_policy import (
    PeerStateCache,
    PeerTrustPolicy,
    PolicyDecision,
    is_always_allowed_peer_tool,
    peer_name_from_tool,
)

logger = logging.getLogger(__name__)


class PeerCallRefused(ToolDenied):
    """Raised when ``PeerTrustPolicy`` blocks an mcp-<peer>-* dispatch."""


class PeerAwareDispatcher(Dispatcher):
    """Pre-flight peer calls against :class:`PeerTrustPolicy`."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        policy: PeerTrustPolicy | None = None,
        cache: PeerStateCache | None = None,
    ) -> None:
        super().__init__(registry)
        self.policy = policy or PeerTrustPolicy()
        self.cache = cache or PeerStateCache()

    async def dispatch(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: DispatchContext | None = None,
    ) -> str:
        peer_name = peer_name_from_tool(tool_name)
        # Non-peer tool, OR always-allowed peer tool → unchanged.
        if peer_name is None or is_always_allowed_peer_tool(tool_name):
            return await super().dispatch(tool_name, args, context)

        ctx = context or DispatchContext()
        peer_state = await self._ensure_peer_state(peer_name)
        result = self.policy.evaluate(peer_state)
        if result.decision is PolicyDecision.REFUSE:
            raise PeerCallRefused(
                f"peer {peer_name!r}: {result.reason}"
            )
        if result.decision is PolicyDecision.DEGRADE:
            logger.info(
                "peer %r: degrading dispatch context to T1 (%s)",
                peer_name,
                result.reason,
            )
            ctx = DispatchContext(
                trust_tier="T1",
                session_id=ctx.session_id,
                allow=ctx.allow,
                deny=ctx.deny,
                elevated=ctx.elevated,
            )
        return await super().dispatch(tool_name, args, ctx)

    async def _ensure_peer_state(self, peer_name: str) -> dict[str, Any] | None:
        cached = self.cache.get(peer_name)
        if cached is not None:
            return cached
        state = await self._fetch_peer_state(peer_name)
        self.cache.put(peer_name, state)
        return state

    async def _fetch_peer_state(self, peer_name: str) -> dict[str, Any] | None:
        """Hit the peer's chimera-kfm-state tool through the BASE dispatcher
        so we don't recurse into this class's policy gate."""
        tool_name = f"mcp-{peer_name}-chimera-kfm-state"
        if self._registry.get(tool_name) is None:
            return None
        try:
            raw = await super().dispatch(tool_name, {}, DispatchContext())
            return json.loads(raw)
        except Exception as exc:
            logger.warning("failed to fetch peer state for %r: %s", peer_name, exc)
            return None
