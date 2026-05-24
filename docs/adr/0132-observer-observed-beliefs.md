# ADR 0132 — Observer/observed belief pairs (Phase 3 / item #1)

**Status**: Accepted (2026-05-24)

**Relationship**: Phase 3 item #1 from [ADR 0123](./0123-honcho-inspired-enhancements.md): *"Observer/observed representation pairs — symmetric belief-state."* Builds on the federation primitives ([`chimera/a2a/peers.py`](../../chimera/a2a/peers.py), [`chimera/a2a/peer_trust_journal.py`](../../chimera/a2a/peer_trust_journal.py)) and the graph schema ([`chimera/memory/graph.py`](../../chimera/memory/graph.py)).

## Context

Honcho's distinguishing data structure is the **representation graph**: belief records keyed by `(observer, observed)`, where the observer is the agent recording the belief and the observed is the agent it's about. Chimera's existing `TRUSTED` graph edge captures only one direction — Chimera's *trust decision* about each peer — and conflates "what we did" with "what we believe".

A symmetric belief layer lets us answer questions like:
- *Has peer alpha drifted away from us?* (their belief about themselves, observed via KFM)
- *Who distrusts whom right now?* (cross-peer queries against the BELIEVES_ABOUT edges)
- *How has alpha's view of itself shifted across rotations?* (time series over the JSONL)

## Design variables (locked via interactive design pass)

| Variable | Choice |
|---|---|
| **Graph schema** | New REL table `BELIEVES_ABOUT(FROM Peer TO Peer, label, drift_score, source, recorded_at)` |
| **Source of beliefs** | Existing KFM snapshot — derived from peer's `last_drift_score` via coarse three-band label |
| **Ingest trigger** | ROTATE phase, alongside peer cards |
| **Persistence** | Append-only JSONL at `mind/peer_beliefs.jsonl` (source of truth; graph projection reads from it) |

## Decision

### Module: `chimera/a2a/peer_beliefs.py`

- **`PeerBelief`** — frozen dataclass: `observer`, `observed`, `label`, `drift_score`, `recorded_at`, `source`, `extra`.
- **`label_for_drift(drift_score)`** — three-band classifier with thresholds tuned to mirror the trust-manager `DEGRADE`/`REFUSE` bands (`< 0.30 → TRUSTS`, `0.30 ≤ x < 0.60 → NEUTRAL`, `≥ 0.60 → DISTRUSTS`, `None → UNKNOWN`). Clamps out-of-range scores defensively.
- **`belief_from_kfm(peer_name, kfm)`** — adapter that turns a KFM dict (from `fetch_peer_kfm`) into a `PeerBelief` with `observer == observed == peer_name`. Stashes `cycle`, `trust_tier`, `plan_kfm_state` in `extra` as provenance.
- **`record_belief(belief, *, mind_dir)`** — appends to `mind/peer_beliefs.jsonl`. JSONL is the durable source of truth.
- **`list_beliefs(*, mind_dir, observer=None, observed=None)`** — reads the journal, skipping malformed lines silently so a crash-mid-write doesn't break readers.
- **`latest_per_pair(*, mind_dir)`** — returns `{(observer, observed): PeerBelief}` (most-recent per pair).

### Graph schema: `chimera/memory/graph.py`

- Adds `BELIEVES_ABOUT(FROM Peer TO Peer, label STRING, drift_score DOUBLE, source STRING, recorded_at STRING)` to `_REL_TABLES`.
- `clear_all` now truncates `BELIEVES_ABOUT` along with the other rel tables.
- New method **`project_beliefs_from_jsonl(*, mind_dir)`** — reads `latest_per_pair` from the JSONL, MERGE-creates Peer nodes for any observer/observed names not yet present, and UNWIND-creates one `BELIEVES_ABOUT` edge per pair. Falls back to a guarded CREATE if the Kuzu build doesn't support MERGE.

### Loop wiring: `chimera/core/loop.py`

- New `_ingest_peer_beliefs_safe()` called from `_phase_rotate` after `_consolidate_peer_cards_safe()`.
- For each peer in `list_peer_chimeras(self._registry)`: `await fetch_peer_kfm(name)` → `belief_from_kfm` → `record_belief`.
- **Default-on**; opt out with `CHIMERA_PEER_BELIEFS_ON_ROTATE=0`.
- **Per-peer failure isolation**: a failing KFM fetch on one peer is logged and skipped; the rest proceed.
- **Outer try/except**: any unhandled error logs WARNING + appends `"ROTATE: peer beliefs failed (…)"` to `phase_log`; rotation completes.
- `phase_log` records `"ROTATE: peer beliefs recorded (N/M peers)"` on success.

## Why peer self-beliefs (observer == observed) first

`fetch_peer_kfm()` returns the peer's *self* state (cycle, trust_tier, plan_kfm_state, last_drift_score) — not their belief about Chimera. True cross-peer beliefs ("what peer A says about peer B", including "what peer A says about Chimera") require federation protocol additions: a new peer-attestation tool (e.g. `mcp-<peer>-chimera-belief-about-me`) that peers explicitly implement. That's a bigger commitment to the wire format than this PR wants to make.

Self-beliefs are still load-bearing:
- The JSONL accumulates a time series per peer that operators can grep.
- The graph supports `MATCH (p:Peer)-[b:BELIEVES_ABOUT]->(p) WHERE b.label = 'DISTRUSTS'` queries today.
- The schema already accepts cross-peer beliefs (observer ≠ observed) — a future PR adds the federation protocol and starts populating them without schema churn.

## Consequences

### Positive

- A typed belief plane the operator and downstream code can query without re-running an LLM.
- Operator-grep-able JSONL at `mind/peer_beliefs.jsonl` mirrors `mind/peer_trust_journal/`, `mind/reflection_conclusions.jsonl`, `mind/peers/*.md` — same operational shape across the Honcho-inspired surface.
- Graph schema is ready for the eventual dialectic API (Phase 3 #2): `peers ask` can `MATCH (a:Peer)-[:BELIEVES_ABOUT]->(b:Peer)` instead of computing belief at query time.
- Failure-isolation discipline matches the rest of the rotate path — beliefs ingest is a bonus signal, never load-bearing.

### Negative

- `_phase_rotate` now does `O(peer_count)` synchronous KFM fetches when the flag is on. Mitigated by rotations being infrequent (≤ once per `max_session_hours`) and per-peer isolation bounding worst-case latency to the slowest single fetch.
- JSONL grows unbounded with each rotation. Acceptable for now: one entry per peer per rotation is ~200 bytes; a year of daily rotations across 10 peers is ~700 KB. Compaction can be a separate chip if it ever bites.
- The "first cut is self-beliefs" framing means cross-peer beliefs sit in the schema unpopulated until the federation protocol catches up. ADR is explicit about this; future PRs land them additively.

## Out of scope (this PR)

- Federation protocol for **true** cross-peer beliefs (peer A's belief about peer B / Chimera) — needs new MCP tool definitions.
- Graph projection wiring into `rebuild_from_sqlite` — callers invoke `project_beliefs_from_jsonl` explicitly (operator CLI or future scheduled refresh).
- A `peers beliefs` CLI verb / dashboard widget — the JSONL is the primary inspection surface today.
- Belief decay / aging — every rotation writes a new row; downstream consumers take the latest via `latest_per_pair`.
- Phase 3 #2 `peers ask` dialectic API — separate chip.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 anchor.
- [ADR 0128 — Peer Cards](./0128-peer-cards.md) — sibling consolidation pattern; same ROTATE-phase trigger discipline.
- [ADR 0129 — Wire Peer Cards into `_phase_rotate`](./0129-peer-cards-rotate-wiring.md) — failure-isolation pattern reused here.
- [ADR 0015 — LadybugDB graph store](./0015-graph-store.md) / [ADR 0017 — graph-edges-v3-1](./0017-graph-edges-v3-1.md) — graph schema conventions.
- [`chimera/a2a/peer_beliefs.py`](../../chimera/a2a/peer_beliefs.py), [`chimera/memory/graph.py`](../../chimera/memory/graph.py), [`chimera/core/loop.py`](../../chimera/core/loop.py).
