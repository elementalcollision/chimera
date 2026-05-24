# ADR 0134 — Hybrid BM25 + vector search: sqlite-vec vs LanceDB (Phase 4 / item #6)

**Status**: Accepted (2026-05-24, research + minimal prototype)

**Relationship**: Phase 4 item #6 from [ADR 0123](./0123-honcho-inspired-enhancements.md): *"Hybrid BM25 + vector search over peer-scoped collections — use sqlite-vec or LanceDB, NOT pgvector. `chimera/wiki_search.py`."* Builds on the FTS5 BM25 index from [ADR 0080](./0080-wiki-fts-search.md).

## Context

Honcho's representation graph supports peer-scoped semantic retrieval via a hybrid BM25 + vector search. Chimera already has the BM25 half (FTS5 over `mind/wiki/`, ADR 0080); the missing piece is the vector half and the fusion layer.

ADR 0123 ruled out pgvector ("no Postgres") and named two candidates for evaluation:

- **sqlite-vec** — C extension for SQLite, in-process, brute-force + optional `vec0` virtual table.
- **LanceDB** — embedded columnar vector DB, IVF/HNSW indexes, Apache 2.0.

This ADR records the comparison and ships a minimal prototype against the chosen backend.

## Evaluation

### Matrix

| Dimension | sqlite-vec | LanceDB |
|---|---|---|
| **Deployment posture** | Reuses existing SQLite connection — zero new daemon, zero new storage tree | Separate storage tree under `state/`; in-process but distinct DB engine |
| **Hybrid composition** | Natural: BM25 (FTS5) lives in the same connection; one transaction joins both | Hybrid via LanceDB's own FTS index OR keep BM25 in SQLite and join paths in Python |
| **Scale ceiling** | Brute-force (~few-thousand docs comfortable; sub-second). `vec0` virtual table for millions | IVF-PQ / HNSW — millions+ comfortably |
| **Dependency weight** | Single PyPI package (`sqlite-vec`); ships the loadable extension binary | `lancedb` + `pyarrow` + `pylance` — heavier dep tree |
| **API surface** | Pure SQL — `SELECT … FROM wiki_vec WHERE …`; familiar shape | Lance-specific Python API; new abstraction to learn |
| **Schema migration story** | Lives in `chimera.db` alongside everything else; backup story is the same SQLite file | Separate database; backup + rebuild story is new |
| **Failure mode if missing** | Module degrades to brute-force pure-Python cosine over raw BLOB column — still correct | Hard dependency; either installed or feature is dead |
| **License** | MIT | Apache 2.0 |

### Workload assumptions

Chimera's near-term retrieval scale, from current corpora:

- `mind/wiki/` — low hundreds of documents.
- ADRs — ~130.
- Peer-scoped collections (when Phase 3 #1 cross-peer beliefs land) — bounded by peer count × belief history. Low thousands worst-case.

We are nowhere near the regime where LanceDB's ANN indexing earns its dep weight. The cap could change if (a) `mind/` grows into the tens of thousands of documents, (b) chunked-per-paragraph embedding becomes standard, or (c) peer-scoped collections accumulate millions of messages.

### Decision

**Pick sqlite-vec.** Reasoning:

1. **Deployment story matches Chimera's posture.** ADR 0123 named the "single binary + SQLite" deployment as a hard constraint when it ruled out pgvector. LanceDB doesn't violate that as starkly as Postgres, but it does add a separate storage engine. sqlite-vec keeps everything in `chimera.db`.
2. **Hybrid is cleaner with both indexes in one connection.** A future `JOIN` between `wiki_fts` and `wiki_vec` (or a single SQL query that ranks both sides) becomes possible. With LanceDB the hybrid path is either Lance's FTS or cross-engine joining in Python.
3. **Scale headroom is sufficient.** Brute-force search over a few thousand documents is sub-second in pure Python; `vec0` is available when we cross 100K vectors. Both well past the current ceiling.
4. **Failure mode degrades gracefully.** Without the sqlite-vec extension installed, the prototype still works (brute-force over a raw-bytes BLOB column). LanceDB has no equivalent.
5. **Lower dep weight.** One PyPI package vs. three.

**Revisit when:** a single peer-scoped collection crosses ~100K documents, or operator surveys show sub-second hybrid queries are no longer fast enough.

## Minimal prototype (this PR)

Ships [`chimera/memory/hybrid_search.py`](../../chimera/memory/hybrid_search.py):

- **`wiki_vec` table** — `(path, dim, embedding BLOB, indexed_at)`. Created idempotently via `ensure_vec_index`.
- **`index_document(conn, path, embedding)`** — upsert one document's vector.
- **`vector_search(conn, query_vec, *, limit)`** — brute-force cosine over the blob column; returns `[(path, similarity)]`. The sqlite-vec extension is loaded opportunistically by `_try_load_sqlite_vec` for future use; the brute-force path is what runs today either way (the interface is stable so a follow-up can swap in `vec0` queries).
- **`hybrid_search_wiki(conn, query, *, embed_fn, limit, rrf_k)`** — runs BM25 (delegating to `search_wiki` from ADR 0080) and vector search, then combines via **Reciprocal Rank Fusion (RRF)** with the canonical `k=60` from Cormack et al. RRF was picked over score-weighted fusion because it sidesteps the normalisation problem (BM25 scores and cosine similarities live in different ranges).
- **`embed_fn` is caller-supplied** — module is provider-agnostic. A follow-up wires a real embedding model (sentence-transformers, OpenAI, local Anthropic, etc.).
- **Feature flag `CHIMERA_HYBRID_SEARCH=1`** — default off. `hybrid_search_wiki` returns an empty list when disabled so opportunistic call sites don't accidentally pay the embedding cost.

The flag-off default means existing `search_wiki` callers (CLI `chimera search`, the dashboard) keep BM25-only behaviour unchanged.

## Consequences

### Positive

- Phase 4 #6's vendor decision is locked with reasoning explicit enough that future contributors can audit the call.
- The prototype works **today** in any Chimera install — sqlite-vec is opportunistic; the module's correctness doesn't depend on it.
- RRF makes the fusion math parameter-light. The only knob is `rrf_k` (default 60); operators don't need to think about score normalisation.
- The schema sits in `chimera.db` so existing backup and migration tooling covers it.

### Negative

- Brute-force scan is O(n×d) per query. Fine at current scale; gets uncomfortable above ~50K vectors. The `vec0` swap is a known follow-up.
- `embed_fn` is unwired in this PR — without a real embedding model, hybrid search has no vector signal. That's deliberate (research-first ships the framing + scaffolding); the embedding-model integration is a separate Phase 4 chip.
- The decision is reversible but not free: switching to LanceDB later would require migrating the indexed corpus. Mitigated by `embed_fn` being external and the on-disk format being a documented little-endian float32 blob.

## Out of scope (this PR)

- A concrete embedding model. Caller passes `embed_fn`; the prototype is satisfied by a deterministic test stub.
- CLI / dashboard exposure of hybrid search. The library API exists; `chimera search --hybrid` lands in a follow-up alongside an embedding-model decision.
- The `vec0` virtual table path. `_try_load_sqlite_vec` is wired but the brute-force path is what runs; converting to `vec0` queries is a separate chip.
- Peer-scoped collections. The first cut indexes the wiki corpus; extending to peer-scoped collections requires a `peer` column on `wiki_vec` (or a separate table) and is named as the next Phase 4 #6 follow-up.
- Phase 4 #8 (LongMemEval / LoCoMo eval harness integration) — a separate research ADR.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 4 anchor; pgvector ruled out.
- [ADR 0080 — mind/wiki FTS5 search](./0080-wiki-fts-search.md) — BM25 substrate this hybrid layer composes with.
- [ADR 0015 — LadybugDB graph store](./0015-graph-store.md) — precedent for embedded specialised storage alongside SQLite.
- [`chimera/memory/hybrid_search.py`](../../chimera/memory/hybrid_search.py), [`chimera/memory/wiki_search.py`](../../chimera/memory/wiki_search.py).
- sqlite-vec: <https://github.com/asg017/sqlite-vec>
- LanceDB: <https://github.com/lancedb/lancedb>
- Cormack, Clarke, Buettcher. *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods* (SIGIR 2009) — the `k=60` RRF default.
