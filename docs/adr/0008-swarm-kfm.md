# ADR 0008 — Swarm-KFM read-only view (v2.3)

**Status:** Accepted. Anchors v2.3. Sits between
[ADR 0006](0006-identity-handshake.md) (identity) and
[ADR 0007](0007-peer-registry.md) (discovery) on one side, and the v2.4
alignment ceremony / cross-agent trust on the other.

## Context

After v2.2 a Chimera can find peers (registry) and know who they are
(identity handshake). Before any *coordination* is possible — let alone
mutual trust gating in v2.4 — peers need a way to ask each other "how
are you doing right now?". Reggio's ontology gives a natural answer:
KFM lifecycle state, cycle number, last drift composite, trust tier.

## Decision: ``chimera-kfm-state`` tool

A second always-exposed tool, alongside ``chimera-identity``:

- **Name:** ``chimera-kfm-state``
- **Toolset:** ``peer``
- **Inputs:** none
- **Returns:** JSON string with:
  - ``cycle`` — last cycle this Chimera completed
  - ``trust_tier`` — name (e.g. ``"T2"``)
  - ``trust_tier_int`` — integer 0..5
  - ``plan_kfm_state`` — current plan entity's KFM state (NEW | EXPERIMENTAL | CANDIDATE | STABLE | DEPRECATED | ARCHIVED | KILLED), or ``null``
  - ``plan_name`` — usually ``"current"``
  - ``plan_state_entered_at_cycle`` — when the plan entered its current state
  - ``last_drift_score`` — composite from the most recent drift assessment, or ``null``
- **Side-effects:** none. The handler reads HEARTBEAT.md frontmatter +
  the SQLite DB + the trust_state.json. No writes. No LLM call.
- **Allow-list bypass:** always exposed, like ``chimera-identity``.

## Why a tool (and not a resource, again)

Same reasoning as ADR 0006: tools route through the existing dispatcher;
resources would need a parallel wire path. The peer dispatch context
(``trust_tier="T1"``, ``session_id="peer"``) provides default-safe
behaviour without any new policy machinery.

## Client side

```python
# chimera/a2a/peers.py
async def fetch_peer_kfm(peer_name, *, registry=None) -> dict: ...
```

The returned dict matches the payload above. v2.4 will *act* on this
(if a peer is at T0 or its plan is DEPRECATED, downstream consumers
may decide to back off). v2.3 only surfaces it.

## Not in v2.3

- **Multi-agent transactions.** A peer's KFM state is informative, not
  authoritative; v2.3 doesn't let peer A demote peer B's plan.
- **Pub/sub.** v2.3 is pull-only. Peers query each other on demand.
  Push-mode (peer broadcasts on its own state change) is a separate
  ADR if/when needed.
- **Alignment ceremony.** Xenocomm's 5 alignment strategies stay v2.4
  work. v2.3 is the data plumbing those strategies will read from.

## References

- [pillar-ontology-drift.md](../research/pillar-ontology-drift.md) — KFM state machine + drift
- [ADR 0006](0006-identity-handshake.md) — identity tool pattern (this ADR mirrors it)
- [chimera/server/kfm_tool.py](../../chimera/server/kfm_tool.py)
- [chimera/a2a/peers.py](../../chimera/a2a/peers.py)
