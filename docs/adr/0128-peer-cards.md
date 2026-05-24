# ADR 0128 — Peer Cards (Phase 3 / item #4)

**Status**: Accepted (2026-05-24, module shipped; loop-wiring follow-up)

**Relationship**: First Phase 3 item from [ADR 0123](./0123-honcho-inspired-enhancements.md) — Honcho's "Peer Cards with periodic consolidation". Built on the trust + federation primitives already in [`chimera/trust/manager.py`](../../chimera/trust/manager.py) and [`chimera/a2a/peer_trust_journal.py`](../../chimera/a2a/peer_trust_journal.py).

## Context

Honcho consolidates a per-peer "card" — a structured, queryable summary of a peer's identity, recent behaviour, and current state — refreshed periodically as a kind of "dream consolidation". Chimera already tracks per-peer trust decisions ([`chimera/a2a/peer_trust_journal.py`](../../chimera/a2a/peer_trust_journal.py)), live KFM snapshots ([`chimera/a2a/peers.py`](../../chimera/a2a/peers.py) `fetch_peer_kfm`), and self-trust state ([`chimera/trust/manager.py`](../../chimera/trust/manager.py)) — but these signals live in three separate places, none of them human-grep-able.

A peer card is the consolidation: pull each signal into one short markdown file per peer, refreshed when the session rotates.

## Design variables (locked via interactive design pass)

The implementation locks the following choices, captured against the operator's selections on 2026-05-24:

| Variable | Choice | Rationale |
|---|---|---|
| **Storage location** | `mind/peers/<peer>.md` per-peer markdown | Human-readable, grep-able, fits the existing `mind/` journal convention. |
| **Refresh trigger** | ROTATE phase only — once per session rotation | Matches Honcho's "dream consolidation" framing. Bounded cost: cards refresh ~daily or on forced rotation. |
| **Construction** | Deterministic aggregation; LLM narrative opt-in via `CHIMERA_PEER_CARD_LLM=1` | Cheapest by default; the narrative layer mirrors the deriver opt-in pattern from [ADR 0125](./0125-wire-deriver-to-reflection.md). |
| **Scope** | Registered federated peers + self-card | Bounded; iterates `list_peer_chimeras()` plus one card for Chimera's view of itself. |
| **Card fields (deterministic)** | Trust label / composite score, recent decisions (last 5), last-seen timestamp, cycles since last contact, last KFM snapshot | All four field groups selected; the schema is documented on `PeerCard`. |
| **LLM narrative scope** (when enabled) | One short paragraph (≤100 words) per peer | Theory-of-mind summary; ~1 sonnet call per peer per rotation. |

## Decision

Ship a new [`chimera/engines/peer_cards.py`](../../chimera/engines/peer_cards.py) module:

- **`PeerCard`** dataclass — typed schema for the deterministic card (peer name, is_self flag, trust label, composite score, recent events, last-seen timestamp, cycles since contact, KFM snapshot, optional narrative).
- **`build_self_card(trust_state)`** — pulls tier / readiness / history from a `TrustState` (duck-typed; the import stays out of the module so tests don't pull in the full trust subsystem).
- **`build_peer_card(peer_name, *, decisions, kfm_snapshot, current_cycle, recent_n)`** — assembles a peer card from a list of `TrustDecisionRecord` and an optional KFM dict.
- **`render_peer_card(card)`** — markdown renderer: H1 with peer name, state table, recent-events list, optional KFM section (suppressed on self-card), optional narrative section.
- **`write_peer_card(mind_dir, card)`** — writes `mind/peers/<safe-name>.md` (sanitising the filename against `../` and shell-unfriendly chars).
- **`consolidate_peer_cards(*, mind_dir, trust_state, peer_names, decisions_by_peer, kfm_by_peer, current_cycle)`** — top-level helper: builds + writes self-card and one card per peer. Every argument is optional so callers can drive the consolidation incrementally (skip KFM fetch when offline, skip self when no `TrustManager`).

The module is **provider-agnostic** — no LLM calls live inside it. The optional narrative paragraph (`PeerCard.narrative`) is populated by the caller, mirroring the [ADR 0124](./0124-deriver-style-extraction.md) deriver pattern.

## Follow-ups (separate chips)

- **Loop wiring** — call `consolidate_peer_cards` from `_phase_rotate` (after rotation fires) in [`chimera/core/loop.py`](../../chimera/core/loop.py). Hot path — gets its own PR so it can be reviewed in isolation.
- **LLM narrative path** — opt-in via `CHIMERA_PEER_CARD_LLM=1`; one sonnet-tier call per peer that fills `PeerCard.narrative` with a ≤100-word theory-of-mind summary.
- **CLI verb** — `chimera peers cards` to consolidate on demand without waiting for ROTATE.

## Consequences

### Positive

- The Phase 3 #4 commitment lands as concrete, testable code without touching the loop hot path.
- The deterministic card already provides operator value (one file per peer, all signals consolidated, grep-able).
- The schema is set up for the dialectic API (Phase 3 #2): cards are the natural object for a future `chimera peers ask "what do we know about Hermes?"` query.

### Negative

- Until the loop-wiring follow-up lands, peer cards only refresh on explicit calls (tests + future CLI verb). Acceptable: the module is the load-bearing piece; the trigger is a tiny addition.
- One more dataclass (`PeerCard`) and one more module (`chimera/engines/peer_cards.py`). Mitigated by the module being narrow and provider-agnostic.

## Out of scope (this PR)

- Hooking `_phase_rotate` to call `consolidate_peer_cards` — follow-up chip.
- The LLM narrative path — follow-up; the slot (`PeerCard.narrative`) exists.
- A CLI verb — follow-up.
- Persisting cards to SQLite or a structured store — kept to markdown per the locked design.
- Items #1 (observer/observed pairs) and #2 (dialectic API) — separate Phase 3 chips.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 commitment.
- [ADR 0124 — Deriver-style structured-output extraction](./0124-deriver-style-extraction.md) — provider-agnostic pattern this module mirrors.
- [ADR 0125 — Wire the Deriver into ReflectionEngine](./0125-wire-deriver-to-reflection.md) — the env-flag opt-in pattern reused for the narrative layer.
- [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md) — original R&D evaluation; item #4 in the net-new list.
