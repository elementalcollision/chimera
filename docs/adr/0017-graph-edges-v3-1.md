# ADR 0017 — Closing the remaining graph edges (v3.1)

**Status:** Accepted (2026-05-18)
**Builds on:** [ADR 0015](0015-graph-store.md), [ADR 0016](0016-graph-powered-features.md)

## Context

After v3.0, three rel tables declared in the v2.10 schema were still empty:
`PROPOSED` (Mutation→Entity), `ACTIVATED` (Mutation→Skill), and `TRUSTED`
(Peer→Peer). v3.1 fills them.

## Decision

### PROPOSED + ACTIVATED — derived from SQLite

- `_project_mutation_edges` (in `chimera/memory/graph.py`) scans each row of
  `mutations` after entities and skills are already projected.
- `PROPOSED` fires when a mutation's payload contains a key in
  `("entity_name", "target", "name")` that matches an existing
  `entities.name`. One edge Mutation→Entity per match.
- `ACTIVATED` fires when `mutations.type == "skill_proposal"` AND
  `mutations.status == "applied"` AND `payload["name"]` matches a projected
  Skill node. One edge Mutation→Skill.
- Skills must be projected before mutation edges, so `rebuild_from_sqlite`
  now calls `_project_skills_and_wiki` before `_project_mutation_edges`.

### TRUSTED — derived from a new peer-trust journal

- New module `chimera/a2a/peer_trust_journal.py` — append-only JSONL under
  `state/peer_trust_journal/{peer}.jsonl` (overridable via
  `CHIMERA_PEER_TRUST_JOURNAL_DIR`). Public API: `record_decision`,
  `list_decisions`, `latest_per_peer`, `trust_journal_dir`,
  `TrustDecisionRecord`.
- `PeerAwareDispatcher` records one decision per non-allow-listed peer
  call (ALLOW / DEGRADE / REFUSE) with the policy reason and last drift
  score. Journal write is best-effort; a failure logs and continues.
- `_project_trust_edges` projects one Self→Peer TRUSTED edge per
  `latest_per_peer()` entry, carrying `drift_score`, `verdict`, and
  `recorded_at`. The local agent's identity becomes a synthetic Peer node
  if it isn't already registered.

### CLI

`chimera graph provenance <mutation-id>` — print the mutation's PROPOSED
entity and ACTIVATED skill (if any).

## Non-goals

- The journal is read-only at v3.1 — no policy reacts to its history yet.
- Cross-host TRUSTED edges (peer-of-peer transitive trust) deferred until
  cross-host sync ships (see ADR 0014's v3 non-goal list).
- We still don't auto-project on every loop tick; rebuild stays explicit.

## Tests

- `tests/test_graph_store.py` adds `test_mutation_edges_projected` and
  `test_trust_journal_round_trip`. Full suite: 415 passing.
