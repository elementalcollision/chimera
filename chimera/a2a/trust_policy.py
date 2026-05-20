"""Cross-agent trust policy — outbound peer-call gating.

Per ADR 0009 (v2.4). Before Chimera dispatches an ``mcp-<peer>-<tool>``
call to a peer (other than the always-allowed handshake/state tools),
the policy looks at the peer's advertised state and decides:

- ``ALLOW``  — proceed
- ``DEGRADE`` — proceed but with the local context downgraded to T1
- ``REFUSE`` — fast-fail, never dispatch

Inputs (all best-effort; missing fields default to "unknown" and the
policy is conservative):

- ``plan_kfm_state``  — DEPRECATED/ARCHIVED/KILLED → REFUSE; CANDIDATE
  or STABLE → ALLOW; otherwise DEGRADE.
- ``trust_tier_int``  — peers at T0 (LOCKED) are refused; T1 supervised
  → DEGRADE; T2+ → ALLOW.
- ``last_drift_score`` — above 0.30 (the same lockdown threshold the
  local drift detector uses) → REFUSE.

The policy module is pure. The TTL cache lives in
:class:`PeerStateCache` so tests can pin a fake clock.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..tools import ToolRegistry

logger = logging.getLogger(__name__)


# Tools that are always allowed regardless of peer state.
_ALWAYS_ALLOWED_SUFFIXES = (
    "-chimera-identity",
    "-chimera-kfm-state",
)


def is_always_allowed_peer_tool(tool_name: str) -> bool:
    """Identity + kfm-state are always callable, even on unhealthy peers."""
    return any(tool_name.endswith(s) for s in _ALWAYS_ALLOWED_SUFFIXES)


def peer_name_from_tool(
    tool_name: str,
    *,
    registry: "ToolRegistry | None" = None,
) -> str | None:
    """Extract the ``<peer>`` segment from ``mcp-<peer>-<rest>``.

    v4.27: peer names containing hyphens (e.g. ``chimera-a``) used to
    silently bypass the trust gate because we split on the first
    hyphen after ``mcp-``. When the caller supplies a ``registry``,
    we now resolve the longest prefix whose ``mcp-<prefix>-chimera-identity``
    tool is actually registered — identity is always exposed, so this
    is the canonical signal that a name is a real peer. Without a
    registry we fall back to the first-segment heuristic (back-compat
    for unit-test callers).
    """
    if not tool_name.startswith("mcp-"):
        return None
    body = tool_name[len("mcp-"):]
    if "-" not in body:
        return None
    if registry is not None:
        parts = body.split("-")
        # Try longest peer-name prefix first; ``mcp-chimera-a-shell`` →
        # candidates "chimera-a-shell" (no), "chimera-a" (yes), "chimera" (yes
        # only if a peer literally named "chimera" is registered). Longest
        # match wins so hyphenated peers don't collide with a single-segment
        # prefix.
        for i in range(len(parts) - 1, 0, -1):
            candidate = "-".join(parts[:i])
            # Either always-allowed peer tool (identity or kfm-state) being
            # registered is a sufficient signal that ``candidate`` is a real peer.
            if (
                registry.get(f"mcp-{candidate}-chimera-identity") is not None
                or registry.get(f"mcp-{candidate}-chimera-kfm-state") is not None
            ):
                return candidate
        return None
    return body.split("-", 1)[0]


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DEGRADE = "degrade"
    REFUSE = "refuse"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str


@dataclass
class PeerTrustPolicy:
    """Rules in one place; trivially adjustable."""

    lockdown_drift_threshold: float = 0.30
    min_trust_tier_for_allow: int = 2   # T2 = UNLOCKED
    refused_plan_states: frozenset[str] = frozenset(
        {"DEPRECATED", "ARCHIVED", "KILLED"}
    )

    def evaluate(self, peer_state: dict[str, Any] | None) -> PolicyResult:
        if peer_state is None:
            return PolicyResult(
                PolicyDecision.DEGRADE, "no peer state available; degrading"
            )
        plan_state = peer_state.get("plan_kfm_state")
        if plan_state in self.refused_plan_states:
            return PolicyResult(
                PolicyDecision.REFUSE,
                f"peer plan state {plan_state!r} disqualifies",
            )
        drift = peer_state.get("last_drift_score")
        if isinstance(drift, (int, float)) and drift >= self.lockdown_drift_threshold:
            return PolicyResult(
                PolicyDecision.REFUSE,
                f"peer drift {drift:.2f} ≥ lockdown threshold",
            )
        tier = peer_state.get("trust_tier_int")
        if isinstance(tier, int):
            if tier <= 0:
                return PolicyResult(
                    PolicyDecision.REFUSE,
                    f"peer trust tier T{tier} (locked) disqualifies",
                )
            if tier < self.min_trust_tier_for_allow:
                return PolicyResult(
                    PolicyDecision.DEGRADE,
                    f"peer trust tier T{tier} below min for allow; degrading",
                )
        if plan_state in {"NEW", "EXPERIMENTAL"}:
            return PolicyResult(
                PolicyDecision.DEGRADE,
                f"peer plan state {plan_state!r} is exploratory; degrading",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok")


@dataclass
class _CacheEntry:
    state: dict[str, Any] | None
    fetched_at: float
    error: str | None = None


class PeerStateCache:
    """TTL-cached peer-state. Avoids one MCP round-trip per dispatch."""

    def __init__(self, *, ttl_seconds: float = 30.0, clock=time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    def get(self, peer_name: str) -> dict[str, Any] | None:
        entry = self._cache.get(peer_name)
        if entry is None:
            return None
        if self._clock() - entry.fetched_at >= self.ttl_seconds:
            self._cache.pop(peer_name, None)
            return None
        return entry.state

    def put(self, peer_name: str, state: dict[str, Any] | None, *, error: str | None = None) -> None:
        self._cache[peer_name] = _CacheEntry(
            state=state, fetched_at=self._clock(), error=error
        )

    def invalidate(self, peer_name: str | None = None) -> None:
        if peer_name is None:
            self._cache.clear()
        else:
            self._cache.pop(peer_name, None)
