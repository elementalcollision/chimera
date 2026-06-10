"""Power-of-two-choices peer selection (ADR 0167).

The A2A dispatch path (:class:`PeerAwareDispatcher`) is *single-target*: the
tool name ``mcp-<peer>-<tool>`` hard-codes which peer is called, and the trust
policy only *gates* that call (ALLOW / DEGRADE / REFUSE). There is **no
candidate selection, no load balancing, no scoring** — when two peers both
advertise a capability, nothing chooses between them.

This module fills that gap with the classic randomized load-balancing result
(Mitzenmacher, "the power of two choices"): when several peers can serve a
request, sample **two at random** and route to the healthier one. Versus
always picking the single best peer this avoids herding every request onto one
node; versus uniform-random it gives an exponential improvement in worst-case
load — at near-zero cost.

The module is additive and **default-OFF**: nothing calls
:func:`select_peer` automatically, so the dispatch path is byte-identical
until a caller opts in via the ``CHIMERA_PEER_SELECTION`` flag and invokes it.

Two layers, so the policy is unit-testable without a federation:

- :func:`choose` — the pure power-of-two-choices rule over already-built
  :class:`PeerCandidate`\\ s, with an injectable RNG.
- :func:`select_peer` — the async orchestrator that enumerates peers, fetches
  their advertised state, applies :class:`PeerTrustPolicy`, folds in
  circuit-breaker health, and calls :func:`choose`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from ..positioning.circuit import CircuitBreaker, CircuitState
from .peers import fetch_peer_identity, fetch_peer_kfm, list_peer_chimeras
from .trust_policy import PeerTrustPolicy, PolicyDecision
from ..config import flag_enabled

if TYPE_CHECKING:
    from ..tools import ToolRegistry

logger = logging.getLogger(__name__)

# Drift assumed for an eligible peer that did not report a numeric drift score.
# Eligible peers are below the lockdown threshold by construction (the policy
# REFUSEs at/above it), so a borderline default loses to any peer with a known
# lower drift while still beating a peer with a known higher one.
_UNKNOWN_DRIFT = 0.30


def peer_selection_enabled() -> bool:
    """Honour ``CHIMERA_PEER_SELECTION`` (default: off, ADR 0167).

    Same parsing shape as ``tool_prefilter_enabled`` (ADR 0165).
    """
    return flag_enabled("CHIMERA_PEER_SELECTION")


@dataclass(frozen=True)
class PeerCandidate:
    """A peer that could serve a request, with its selection signals."""

    name: str
    drift_score: float | None = None
    healthy: bool = True  # circuit breaker not OPEN

    def load_key(self) -> tuple[int, float]:
        """Sort key — lower is better.

        Healthy peers always sort ahead of unhealthy ones; within a health
        class the lower-drift (less-loaded / more-trusted) peer wins.
        """
        drift = self.drift_score if isinstance(self.drift_score, (int, float)) else _UNKNOWN_DRIFT
        return (0 if self.healthy else 1, float(drift))


def choose(
    candidates: list[PeerCandidate],
    *,
    rng: random.Random | None = None,
) -> PeerCandidate | None:
    """Power-of-two-choices selection over eligible candidates.

    - 0 candidates → ``None`` (caller has no peer to route to).
    - 1 candidate  → that candidate.
    - ≥2 candidates → sample two distinct candidates uniformly at random and
      return the one with the better :meth:`PeerCandidate.load_key`. Ties
      break toward the first sampled, which is itself random, so no peer is
      structurally favoured.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    r = rng or random
    a, b = r.sample(candidates, 2)
    return a if a.load_key() <= b.load_key() else b


def _breaker_healthy(breaker: CircuitBreaker | None) -> bool:
    """A peer is healthy unless its circuit breaker is OPEN (non-mutating read)."""
    return breaker is None or breaker.state is not CircuitState.OPEN


async def _candidate_for(
    peer: str,
    capability: str | None,
    *,
    registry: "ToolRegistry | None",
    policy: PeerTrustPolicy,
    breakers: Mapping[str, CircuitBreaker] | None,
) -> PeerCandidate | None:
    """Build a candidate for ``peer``, or ``None`` if it is ineligible.

    Ineligible = trust policy REFUSEs, or (when a capability is requested) the
    peer does not advertise it, or its state could not be fetched.
    """
    try:
        state = await fetch_peer_kfm(peer, registry=registry)
    except Exception as exc:  # LookupError, transport failure, bad JSON
        logger.debug("peer-selection: skipping %r (kfm fetch failed: %s)", peer, exc)
        return None

    if policy.evaluate(state).decision is PolicyDecision.REFUSE:
        return None

    if capability is not None:
        try:
            identity = await fetch_peer_identity(peer, registry=registry)
        except Exception as exc:
            logger.debug("peer-selection: skipping %r (identity fetch failed: %s)", peer, exc)
            return None
        advertised = identity.get("capabilities") or ()
        if capability not in set(advertised):
            return None

    drift = state.get("last_drift_score")
    breaker = breakers.get(peer) if breakers else None
    return PeerCandidate(
        name=peer,
        drift_score=drift if isinstance(drift, (int, float)) else None,
        healthy=_breaker_healthy(breaker),
    )


async def select_peer(
    capability: str | None = None,
    *,
    registry: "ToolRegistry | None" = None,
    policy: PeerTrustPolicy | None = None,
    breakers: Mapping[str, CircuitBreaker] | None = None,
    rng: random.Random | None = None,
) -> str | None:
    """Pick a peer to serve ``capability`` via power-of-two-choices.

    Enumerates registered peer Chimeras, drops any the trust policy would
    REFUSE (or that does not advertise ``capability`` when one is given),
    folds in circuit-breaker health, and applies :func:`choose`. Returns the
    selected peer name (the ``<peer>`` segment, ready to compose into
    ``mcp-<peer>-<tool>``) or ``None`` when no eligible peer exists.

    Honours nothing about the flag itself — callers gate on
    :func:`peer_selection_enabled`; this stays pure so it can be tested and
    reused. Peer-state fetches run concurrently.
    """
    pol = policy or PeerTrustPolicy()
    peers = list_peer_chimeras(registry)
    if not peers:
        return None

    results = await asyncio.gather(
        *(
            _candidate_for(
                p, capability, registry=registry, policy=pol, breakers=breakers
            )
            for p in peers
        )
    )
    candidates = [c for c in results if c is not None]
    chosen = choose(candidates, rng=rng)
    if chosen is None:
        logger.info(
            "peer-selection: no eligible peer for capability %r (of %d known)",
            capability,
            len(peers),
        )
        return None
    return chosen.name
