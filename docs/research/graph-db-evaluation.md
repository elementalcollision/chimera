# Graph DB evaluation for Chimera

_Research deliverable. Decision lives in [ADR 0015](../adr/0015-graph-store.md) once approved._

## TL;DR
- **Pair LadybugDB (formerly Kuzu, fork) with Qdrant.** Ladybug for the 5 graph-shaped use cases; Qdrant only when ADR 0002's 50% context-window trigger fires.
- Do **not** adopt HelixDB v1: it's a server (port 6969), full ACID lives only behind Enterprise/object-storage, OSS roadmap still lists "ACID Compliance" as Phase 5 future.
- Do **not** adopt LanceDB as a graph store: `lance-graph` is a Rust crate with no Python API, executes Cypher as DataFusion SQL joins, and the maintainers' own positioning is "skip the graph DB, do graph in your app layer."

## Candidates at a glance

| Name | Type | Embedded? | Query lang | Vector | Active dev? | Maturity | Best fit | Gotchas |
|---|---|---|---|---|---|---|---|---|
| **KuzuDB** | Property graph | Yes (in-process) | Cypher | Yes (HNSW, v0.9+) | **Archived Oct 2025** (acquired by Apple) | High but frozen | — | Do not pick the upstream repo; pick Ladybug |
| **LadybugDB** | Property graph (Kuzu fork) | Yes (in-process) | Cypher | Yes | Yes (v0.16.1 May 2026, 70 contributors, includes original Kuzu team) | New name, mature code | KFM history, provenance, peer-trust, skill-dep | <1 year of fork history; name not yet established |
| **HelixDB** | Graph+vector hybrid | **No — runs as server** on :6969 | HelixQL (Rust DSL) | Native | Yes, fast-moving | Young (helix-py 0.2.x, weekly releases) | Graph+vector in one store *if* you accept a server | OSS ACID is unclear; full ACID is Enterprise-only; would need a sidecar process; Python SDK is a thin client |
| **LanceDB** | Columnar vector store | Yes (file-based) | SQL `where` + vector search; `lance-graph` Cypher in Rust only | Native | Yes | Mature for vectors; graph layer is experimental | Embedding recall, payload-filtered vector | `lance-graph` has no Python API; multi-hop traversal slower than Kuzu/Ladybug (q8: 126ms vs 6.5ms) |
| **Qdrant** | Vector DB | No (server, but local docker is trivial) | Filter DSL | Native, best-in-class HNSW | Yes | Production | Embedding recall #6 only | Not a graph DB; "graph walks via denormalized payloads" is a hack |

## How each fits the 6 use cases

**KuzuDB / LadybugDB.** Wins use cases 1–4 cleanly. Cypher over `entity_transitions` collapses KFM-history queries from recursive CTEs to one `MATCH (p:plan)-[t:TRANSITION*]->()` line; provenance is the canonical multi-hop join (~6.5ms for 2-hop on social-graph scale per `prrao87/graph-benchmark`); peer-trust and skill-dep are tiny graphs but get visualization for free via G.V() integration. Use case 5 (mind/wiki) is doable but awkward — markdown link extraction → node insertion is custom. Use case 6 is supported (v0.9 added HNSW vector index in-DB), good enough to defer Qdrant longer. **Integration shape:** `state/chimera.graph/` directory, `kuzu.Database()` opened alongside existing `sqlite3.connect("state/chimera.db")`, re-derived from SQLite on first run via `COPY FROM` Parquet/CSV exports.

**HelixDB.** Use cases 1–4 are technically expressible in HelixQL, and use case 6 is native (vector type `V::` first-class). But: Chimera is currently a single-process Python agent with SQLite — adding a Rust server on :6969 + an `Instance` lifecycle wrapper inverts the operational shape. Helix's MCP exposure (`n_from_type`, `out_step`) is attractive for swarm peers querying each other's graphs, but the OSS roadmap still lists ACID as future work and the docs only guarantee full ACID/durability on Enterprise (object-storage backed). Premature for Chimera's risk profile.

**LanceDB.** Use case 6 is its home turf. Use cases 1–5: `lance-graph` is a Rust crate (`crates.io/crates/lance-graph` v0.5.4) — no Python bindings yet, and even in Rust its semantic surface is parsed-but-not-executed (OPTIONAL MATCH, subqueries unimplemented). Maintainers' own benchmark shows lance-graph slower on real multi-hop. **Integration shape:** would need to model `entities`/`entity_transitions` as Lance tables and traverse via repeated SQL joins from Python — strictly worse than keeping it in SQLite.

**Qdrant.** Use case 6 only. The "graph walk via denormalized payloads" pattern (charleschen.ai wiki) works for shallow seeded expansion but is exactly the anti-pattern Chimera should avoid for KFM/provenance — you lose Cypher and you re-serialize relations into JSON payloads on every migration.

## Operational trade-offs

| | Process model | Backup | Multi-host | Latency at our scale |
|---|---|---|---|---|
| Ladybug | In-process, single `.kz` directory | `cp -r state/chimera.graph/` | N/A (single-user) | sub-ms for our row counts |
| HelixDB | Sidecar daemon (`helix` CLI starts it) | Object-storage on Enterprise; OSS unclear | Built for it, overkill here | sub-ms but +network hop |
| LanceDB | In-process, file-based | Lance is versioned (time-travel built-in) | S3-native | Vector ~1ms; "graph" via joins is unpredictable |
| Qdrant | Docker container, single node fine | Snapshot API | Cluster mode exists | <10ms vector |

Write-amplification: Ladybug writes columnar + CSR adjacency; Helix appends to RocksDB-style log + vector index. Both fine at Chimera's write rate (<10 KFM transitions/cycle).

## Recommendation

**Adopt LadybugDB now as the graph store; defer Qdrant.** Ladybug carries the Kuzu codebase forward (same authors as the VLDB papers, v0.16.1 May 2026, 70 contributors), keeps the in-process model that matches Chimera's "SQLite + filesystem" shape, gives us Cypher for use cases 1–4, and ships a usable vector index (Kuzu 0.9.0 `LOAD VECTOR;` HNSW) that buys us additional runway against ADR 0002's deferral trigger.

Pick **Qdrant** for use case 6 **only if and when** either (a) ADR 0002's "prompt context regularly >50% of model max" trigger fires, **or** (b) Ladybug's in-DB HNSW recall benchmarks fall below 0.9 on our CHRONICLE+notes corpus at >100k chunks. Until then, Ladybug's vector index is sufficient.

Reject **HelixDB** for v2.x (revisit when their OSS Roadmap Phase 5 "ACID Compliance" ships and a non-server embedded mode exists). Reject **LanceDB-as-graph** until `lance-graph` has a Python binding and executes OPTIONAL MATCH.

## What v2.x ADR 0015 should commit to

- **Location:** `state/chimera.graph/` (Ladybug database directory), peer-coordinate with `state/chimera.db`.
- **Schema:** node tables `Entity`, `Mutation`, `ApiCall`, `Peer`, `Skill`, `WikiDoc`; rel tables `TRANSITIONED_TO` (carries `from_state`, `to_state`, `operator_type`, `cycle`), `PROPOSED`, `ACTIVATED`, `TRUSTED` (weighted by drift score), `DEPENDS_ON`, `REFERENCES`.
- **Source of truth:** SQLite remains authoritative for `entities`, `entity_transitions`, `mutations`, `api_calls`. Graph is a **derived projection**, rebuildable from SQLite + `~/.chimera/peers/` + AST scan of `chimera/tools/dynamic/*.py` + markdown link parse of `mind/`.
- **Migration story:** one-shot `scripts/build_graph.py` that issues `COPY entities FROM ... (FORMAT CSV)`; idempotent; safe to delete and rebuild.
- **What lives only in the graph:** skill-dependency edges (AST-derived), wiki cross-reference edges (markdown-derived), peer-trust weighted edges over time. These have no SQLite home today.
- **Rebuild trigger:** any schema migration on SQLite invalidates the graph; chronicle a `graph_schema_version` row in `entities` details.
- **Vector deferral:** record the trigger restated — switch to Qdrant when either context >50% or Ladybug HNSW recall@10 <0.9 on a 100k-chunk corpus.
- **Operator surface:** a `chimera graph query "MATCH ..."` CLI verb; results piped through the same mutation/approval workflow as everything else.

## Sources

- Ladybug fork announcement: [blog.ladybugdb.com](https://blog.ladybugdb.com/post/ladybug-spreading-its-wings/), [ladybugdb.com/faq.html](https://ladybugdb.com/faq.html)
- Kuzu 0.9.0 release with HNSW: [blog.kuzudb.com](https://blog.kuzudb.com/post/kuzu-0.9.0-release/)
- Graph benchmark numbers: [github.com/prrao87/graph-benchmark](https://github.com/prrao87/graph-benchmark)
- HelixDB Python SDK: [docs.helix-db.com](https://docs.helix-db.com/documentation/sdks/helix-py)
- HelixDB ACID-on-Enterprise: [docs.helix-db.com/enterprise/guarantees](https://docs.helix-db.com/enterprise/guarantees)
- HelixDB OSS roadmap: [github.com/HelixDB/helix-db/wiki/Roadmap](https://github.com/HelixDB/helix-db/wiki/Roadmap)
- LanceDB graph crate: [crates.io/crates/lance-graph](https://crates.io/crates/lance-graph)
- LanceDB's "skip graph DB" positioning: [lancedb.com/lp/graphrag-database-vs-lancedb-enterprise](https://lancedb.com/lp/graphrag-database-vs-lancedb-enterprise/)
- Qdrant payload filtering: [qdrant.tech/documentation/concepts/payload](https://qdrant.tech/documentation/concepts/payload/)
- Qdrant + Neo4j GraphRAG: [qdrant.tech/documentation/examples/graphrag-qdrant-neo4j](https://qdrant.tech/documentation/examples/graphrag-qdrant-neo4j/)
