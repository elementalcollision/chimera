# ADR 0009 — Cross-agent trust (outbound) (v2.4)

**Status:** Accepted. Anchors v2.4. Builds on the data plumbing of
[ADR 0008](0008-swarm-kfm.md) (swarm-KFM read-only view).

## Context

After v2.3, a Chimera *knows* what its peers say about themselves
(identity, KFM state, trust tier, drift). v2.4 makes that data
actionable: before calling a peer's tool, the local Chimera consults
its peers' advertised state and decides ALLOW / DEGRADE / REFUSE.

This is the *outbound* half of cross-agent trust. The inbound half —
where this Chimera decides what trust tier an incoming peer-typed
call runs at — is harder and stays v2.x because stdio gives us no
strong attestation. v2.4's safe default for inbound remains
``DispatchContext(trust_tier="T1")`` from v2.0.

## Decision

A new pure module ``chimera/a2a/trust_policy.py`` holds two pieces:

### 1. ``PeerTrustPolicy``

Pure function on a peer state dict:

| Peer condition | Decision | Why |
|---|---|---|
| ``plan_kfm_state`` ∈ {DEPRECATED, ARCHIVED, KILLED} | REFUSE | peer's plan is decomissioning; calling it is calling a corpse |
| ``last_drift_score`` ≥ 0.30 (same threshold the local detector uses for lockdown) | REFUSE | peer is in or near lockdown |
| ``trust_tier_int`` == 0 (T0/LOCKED) | REFUSE | peer is observer-only |
| ``trust_tier_int`` < 2 (below T2/UNLOCKED) | DEGRADE | proceed but pass down trust_tier="T1" |
| ``plan_kfm_state`` ∈ {NEW, EXPERIMENTAL} | DEGRADE | exploratory; proceed cautiously |
| otherwise | ALLOW | |
| state is ``None`` (failed to fetch) | DEGRADE | conservative default |

Thresholds and the refused-state set are dataclass fields; operators
can tune by constructing a ``PeerTrustPolicy(...)`` with overrides.

### 2. ``PeerStateCache``

TTL cache (default 30 s) keyed by peer server-name. Avoids one MCP
round-trip per outbound call. ``invalidate(peer_name)`` clears one entry;
``invalidate()`` (no arg) clears all.

### 3. Identity + kfm-state are always allowed

``is_always_allowed_peer_tool(name)`` returns True for any tool ending
in ``-chimera-identity`` or ``-chimera-kfm-state``. Even a REFUSED peer
must be reachable for its state to be re-fetched. Without this rule
the policy would lock itself out.

## What v2.4 *doesn't* do

- **Doesn't wire the policy into the dispatcher.** v2.4 ships the
  policy + cache as pure modules with unit tests. Wiring them into
  every ``mcp-*`` dispatch path (or into ``ActExecutor`` specifically)
  is a follow-up. The motivation for splitting: the policy is the
  decision; how/where to enforce is a separate question (per-call
  pre-flight in the dispatcher? a wrapper handler at registration
  time? both?). The right shape comes after we have one concrete
  call site to fit it to.
- **Doesn't handle inbound attestation.** Inbound stays
  ``trust_tier="T1"`` from v2.0. Real inbound attestation needs HTTP
  + auth tokens (a future ADR).
- **Doesn't sign anything.** Peer-advertised state is unsigned. A
  malicious peer can lie about its KFM state. v2.x will tackle
  signing once a peer-registry-as-authority exists.

## References

- [ADR 0006](0006-identity-handshake.md) — identity data the policy consumes
- [ADR 0008](0008-swarm-kfm.md) — KFM state data the policy consumes
- [chimera/a2a/trust_policy.py](../../chimera/a2a/trust_policy.py)
- [pillar-ontology-drift.md](../research/pillar-ontology-drift.md) §"Pattern 4: Graduated drift response" — the local drift→action table this mirrors at the cross-agent layer
