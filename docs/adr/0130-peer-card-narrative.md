# ADR 0130 — Peer-Card LLM Narrative Layer (opt-in)

**Status**: Accepted (2026-05-24)

**Relationship**: Closes the second follow-up named in [ADR 0128 §"Follow-ups"](./0128-peer-cards.md): *"opt-in via `CHIMERA_PEER_CARD_LLM=1`; one sonnet-tier call per peer that fills `PeerCard.narrative` with a ≤100-word theory-of-mind summary."*

## Context

[ADR 0128](./0128-peer-cards.md) shipped the deterministic peer-card module and reserved a `narrative` slot on `PeerCard` for an opt-in LLM-generated paragraph. [ADR 0129](./0129-peer-cards-rotate-wiring.md) wired the deterministic consolidation into `_phase_rotate`. The narrative layer was deliberately deferred.

The narrative layer is the difference between "a structured snapshot of trust + drift signal" and Honcho's full "Peer Card" — a theory-of-mind summary an operator (or downstream code) can read at a glance.

## Decision

Add two functions to [`chimera/engines/peer_cards.py`](../../chimera/engines/peer_cards.py):

- **`build_narrative_prompt(card) -> str`** — renders `PEER_CARD_NARRATIVE_PROMPT` with the card's fields. Optional / numeric fields render with safe fallbacks (`"(unknown)"`, `"(none)"`) so the prompt is always well-formed even on a half-empty card.
- **`apply_narrative(card, response_text) -> PeerCard`** — strips markdown fences if the model added one anyway, caps the result at ~120 words (100 with 20-word slack for "under 100 words" overshoot), and assigns to `card.narrative`. Empty response leaves `narrative` unset.

The module **does not make LLM calls** — same provider-agnostic discipline as the deriver (ADR 0124). The caller (loop or future CLI verb) runs the provider.

Wire the loop:

- **`ChimeraLoop._enrich_cards_with_narratives(cards)`** in [`chimera/core/loop.py`](../../chimera/core/loop.py) — called from `_consolidate_peer_cards_safe` when `CHIMERA_PEER_CARD_LLM` is set to `1|true|yes|on`.
- One sonnet-tier call **per card** (self + each peer). Uses the same `select_rung("sonnet")` resolution path as the daily engines.
- **Per-card failure isolation.** A provider exception on one card logs a warning and continues with the next; the deterministic body is still written.
- **No providers → skip silently.** When `self._act is None` or `providers` is empty, narratives are skipped and the rotation logs `"ROTATE: peer card narratives skipped (no providers)"`.
- Defaults to **off**. Narrative cost is `O(peer_count + 1)` sonnet calls per rotation — bounded but real. Operator chooses when to pay it.

## Why sync, not async

The loop's `_phase_rotate` already runs sync (it's called from the async cycle but does no I/O of its own beyond file writes). Spinning up an async task for narratives would either (a) block rotation until done (sync wrapper) or (b) leave a fire-and-forget task that might be orphaned on shutdown. The locked design picked the simplest viable wiring; if narrative latency becomes a problem in practice, the async path is a future enhancement.

## Consequences

### Positive

- Peer cards now have the Honcho-faithful "theory-of-mind paragraph" when operators opt in.
- The opt-in flag composes with the on-rotate flag: operators can turn deterministic refresh off-or-on independently from narrative cost.
- Per-card isolation means one bad peer name or transient provider error doesn't strand the whole rotation.

### Negative

- Narrative cost scales linearly with peer count. Mitigated by being opt-in and by the prompt being short (a few hundred tokens in, ≤100 words out).
- Sync execution means rotation now blocks on `peer_count + 1` model calls when the flag is on. Acceptable for daily-ish rotations; revisit if rotation frequency grows.
- The asyncio handling — `asyncio.run(_call(prompt))` per card — assumes no running event loop in this stack frame. True today inside `_phase_rotate`, but worth watching if the loop ever becomes re-entrant.

## Out of scope (this PR)

- The `chimera peers cards` CLI verb — follow-up #3.
- Async / batched narrative calls (sync only here).
- Caching narratives between rotations (every rotation re-asks).
- Narratives for non-registered peers — out of locked scope (ADR 0128).

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 #4 anchor.
- [ADR 0124 — Deriver-style structured-output extraction](./0124-deriver-style-extraction.md) — provider-agnostic pattern mirrored here.
- [ADR 0128 — Peer Cards module](./0128-peer-cards.md) — schema this layer fills.
- [ADR 0129 — Wire Peer Cards into `_phase_rotate`](./0129-peer-cards-rotate-wiring.md) — the rotation hook this layer plugs into.
- [`chimera/engines/peer_cards.py`](../../chimera/engines/peer_cards.py) — `build_narrative_prompt`, `apply_narrative`.
- [`chimera/core/loop.py`](../../chimera/core/loop.py) — `_enrich_cards_with_narratives`.
