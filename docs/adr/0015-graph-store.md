# ADR 0015 — LadybugDB graph store

**Status:** Accepted (2026-05-18)
**Supersedes:** none
**Depends on:** [ADR 0002](0002-memory-strategy.md), [ADR 0003](0003-memory-strategy-amendment.md)

## Context

Chimera persists its ontology and activity log in SQLite (`state/chimera.db`) plus a markdown-mind filesystem under `mind/`. As the agent accumulates KFM history, mutations, peer-trust events, dynamic-skill dependencies, and wiki cross-references, more questions become naturally *graph-shaped*:

1. "What is the full lifecycle of plan X?" — chain of `entity_transitions` rows.
2. "Which mutations led to which skills, and which of those still run?" — provenance.
3. "Which peers do we trust transitively, weighted by drift score?" — peer-trust graph.
4. "Which skills depend on which other skills?" — AST-derived edges.
5. "Which wiki notes cross-reference each other?" — markdown link graph.
6. *(future)* "Find embeddings semantically near this chunk." — vector recall.

All six are expressible in SQLite with recursive CTEs and JSON payloads but get verbose fast. The research deliverable in `docs/research/graph-db-evaluation.md` surveys KuzuDB, LadybugDB, HelixDB, LanceDB, and Qdrant.

## Decision

- **Adopt LadybugDB** (the active Kuzu fork — Apple acquired and archived upstream Kuzu in October 2025) as Chimera's graph store.
- **SQLite remains the source of truth** for `entities`, `entity_transitions`, `mutations`, `api_calls`. The graph is a **derived projection**, rebuildable from SQLite + the filesystem peer registry.
- Use the `kuzu` PyPI package (>=0.10) during the Ladybug rebrand; pin tighter once Ladybug ships its own wheel.
- **Defer Qdrant** until either (a) [ADR 0002](./0002-memory-strategy.md)'s "prompt context regularly >50% of model max" trigger fires, or (b) Ladybug's in-DB HNSW recall@10 falls below 0.9 on a 100k-chunk corpus. Reject HelixDB (OSS ACID unclear, server-only) and LanceDB-as-graph (`lance-graph` is Rust-only).

## Shape

- **Location:** `state/chimera.graph/` (a Ladybug database directory), peer of `state/chimera.db`.
- **Node tables:** `Entity`, `Mutation`, `ApiCall`, `Peer`, `Skill`, `WikiDoc`.
- **Rel tables:** `TRANSITIONED_TO` (carries `from_state`, `to_state`, `operator_type`, `cycle`, `created_at`), `PROPOSED` (Mutation→Entity), `ACTIVATED` (Mutation→Skill), `TRUSTED` (Peer→Peer, weighted by drift score), `DEPENDS_ON` (Skill→Skill, AST-derived), `USES_TOOL` (Skill→Entity), `REFERENCES` (WikiDoc→WikiDoc, markdown-link-derived).
- **Schema version:** `GRAPH_SCHEMA_VERSION = 1` in `chimera/memory/graph.py`. Any SQLite schema migration invalidates the graph; rebuild is one CLI call.

## Surface

- `chimera.memory.GraphStore` — wraps `kuzu.Database` + `kuzu.Connection`.
- `GraphStore.init_schema()` — idempotent CREATE NODE/REL TABLE IF NOT EXISTS.
- `GraphStore.query(cypher, params=...)` → `GraphQueryResult{columns, rows}`.
- `GraphStore.rebuild_from_sqlite(sqlite_conn)` → counts per node/rel type.
- CLI: `chimera graph init`, `chimera graph rebuild`, `chimera graph query "<cypher>"`.
- One-shot: `python -m scripts.build_graph`.

## What lives only in the graph

- Skill-dependency edges (AST scan of `chimera/tools/dynamic/*.py`).
- Wiki cross-references (markdown link parse of `mind/`).
- Peer-trust edges weighted over time (drift score on each `TRUSTED` edge).

These have no SQLite home today; the graph is their primary store. If we lose `state/chimera.graph/` we re-derive these from filesystem scans, so durability matches SQLite's.

## Non-goals

- The graph is not yet the source of truth for any KFM operation. Loop dispatch reads from SQLite.
- We do not yet exercise Ladybug's HNSW vector index — that comes when the Qdrant deferral trigger flips.
- No automatic on-write projection. Rebuild is explicit (CLI or scheduled).

## Tests

- `tests/test_graph_store.py` — schema init idempotence, rebuild count correctness, `TRANSITIONED_TO` edge projection, idempotent rebuild, query columns/rows shape.

## Sources

- Research deliverable: [`docs/research/graph-db-evaluation.md`](../research/graph-db-evaluation.md)
- Ladybug fork: [ladybugdb.com/faq.html](https://ladybugdb.com/faq.html)
- Kuzu 0.9.0 HNSW release notes.
