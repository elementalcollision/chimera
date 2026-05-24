# ADR 0129 — Wire Peer Cards into `_phase_rotate`

**Status**: Accepted (2026-05-24)

**Relationship**: Closes the first follow-up named in [ADR 0128 §"Follow-ups"](./0128-peer-cards.md): *"Call `consolidate_peer_cards` from `_phase_rotate` (after rotation fires) in `chimera/core/loop.py`."*

## Context

[ADR 0128](./0128-peer-cards.md) shipped the peer-cards module without touching the loop hot path. Without a trigger, cards only refresh on explicit calls (tests + the future CLI verb), defeating the "periodic consolidation" framing borrowed from Honcho's dream-consolidation pattern.

The locked design from ADR 0128 says: **ROTATE phase only**. Time to wire it.

## Decision

Add a `_consolidate_peer_cards_safe()` method to `ChimeraLoop` in [`chimera/core/loop.py`](../../chimera/core/loop.py) and call it from `_phase_rotate` immediately after rotation fires (after the heartbeat + session-log writes, before the `_log_phase("ROTATE: rotated …")` line).

Behaviour:

- **Default-on.** Opt out with `CHIMERA_PEER_CARDS_ON_ROTATE=0` (also accepts `false`, `no`, `off`, case-insensitive). Default-on is correct because consolidation reads existing state and writes per-peer markdown — there's no LLM call in this PR, so cost is bounded by `len(peer_names)` file writes.
- **Sync, KFM-skipped.** The loop call passes `peer_names` (from `list_peer_chimeras(self._registry)`), `decisions_by_peer` (from `list_decisions(peer)`), `trust_state`, and `current_cycle`. It does **not** fetch live KFM snapshots — `fetch_peer_kfm` is async and a per-peer network call; that's a separate follow-up (and ADR 0128 already names it).
- **Failure-isolated.** The entire call is wrapped in `try/except`. Any exception is logged at WARNING and recorded in `phase_log` (`"ROTATE: peer cards failed (…)"`); rotation itself proceeds. Rotation is the load-bearing operation; cards are a bonus signal.
- **Order.** Cards are consolidated **after** the heartbeat + session-log writes so a card-consolidation crash cannot leave the rotation half-applied.

## Why default-on

Peer cards are passive observers — they read from existing journals (trust_events, peer_trust_journal, TrustState) and write to `mind/peers/`. There is no network I/O in this PR. Default-on matches the "make the new behaviour visible by default" preference established by ADR 0125 for deriver-style features when cost is bounded. Operators who want to disable it for any reason (e.g. read-only filesystem) have the env flag.

## Consequences

### Positive

- Peer cards now actually refresh on rotation, closing the Phase 3 #4 loop end-to-end.
- The failure-isolation pattern preserves rotation correctness — a future bug in the cards module can't strand a session.
- A `phase_log` entry surfaces the refresh in the cycle report so operators can see it ran without grepping the filesystem.

### Negative

- Hot path touch: `_phase_rotate` now does measurably more work on rotation events. Mitigated by rotations being infrequent (≤ once per `max_session_hours`) and by the consolidation being O(peer_count) markdown writes.
- The async KFM fetch is deferred — cards refreshed at rotation do not include live `plan_kfm_state`. Acceptable: trust+drift signal is the load-bearing payload; KFM is enrichment.

## Out of scope (this PR)

- Async KFM fetch in the rotate path (follow-up; sync-only here).
- LLM narrative path (`CHIMERA_PEER_CARD_LLM=1`) — separate follow-up, will land alongside the CLI verb.
- `chimera peers cards` CLI verb — separate follow-up.
- Cards for non-registered peers (ever-seen but no longer in the federation registry) — out of locked scope.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 #4 anchor.
- [ADR 0128 — Peer Cards module](./0128-peer-cards.md) — the consolidation pieces this PR triggers.
- [`chimera/core/loop.py`](../../chimera/core/loop.py) — `_phase_rotate`, `_consolidate_peer_cards_safe`.
- [`chimera/engines/peer_cards.py`](../../chimera/engines/peer_cards.py) — `consolidate_peer_cards`.
