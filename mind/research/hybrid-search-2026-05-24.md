# Hybrid BM25 + vector search — research note (2026-05-24)

**Scope**: Phase 4 #6 of the Honcho-inspired roadmap (ADR 0123). Long-form vendor evaluation, workload assumptions, fusion-math design notes, and named follow-ups for #6.b (real-embedding integration). The ADR (`docs/adr/0134-hybrid-search-eval.md`) captures only the locked-design summary; this note is the source of truth for the evaluation reasoning.

## Why hybrid?

The wiki corpus is already searchable via FTS5 BM25 (ADR 0080). BM25 is excellent for lexical recall — exact terms, well-formed queries, technical jargon — but degrades on paraphrase and synonymy. A vector index addresses the converse: it catches semantic neighbours of the query that BM25 misses because the surface forms diverge.

Honcho's representation graph composes both. The "right" hybrid behaviour for Chimera mirrors that: a single `HybridSearcher.search()` that returns the union of BM25 and vector hits, ranked by a fusion that doesn't require the operator to pick `alpha` weights.

## Vendor evaluation: sqlite-vec vs. LanceDB

ADR 0123 ruled out pgvector ("no Postgres") and named two candidates. Both are embedded; neither adds a daemon. The differences matter at three layers: deployment posture, hybrid composition, and dependency weight.

### Deployment posture

| Aspect | sqlite-vec | LanceDB |
|---|---|---|
| Storage location | Inside `chimera.db` (existing SQLite file) | New tree under `state/` (`*.lance` files) |
| Backup story | Already covered by SQLite backup | Needs new backup path |
| Migration story | One DB to migrate | Two DBs to keep in sync |
| New daemon? | No (extension loaded in-process) | No (in-process Rust lib) |
| Connection lifecycle | Same connection as the rest of the agent | Separate `lancedb.connect()` |

sqlite-vec wins on every line except where they tie (no new daemon). The "one DB file" property is structurally similar to why ADR 0123 ruled out pgvector — keeping all of Chimera's state in one SQLite file is a posture choice, not just an aesthetic one. It simplifies operator runbooks (one file to copy when reproducing a state for debugging), graph-tooling (ADR 0015's Kuzu projection reads from SQLite), and rebuild flows.

### Hybrid composition

The fusion layer needs to see both BM25 and vector results. With sqlite-vec, both indexes live in the same `sqlite3.Connection`, so a future cross-source query can be a single SQL statement:

```sql
WITH bm25 AS (
  SELECT path, bm25(wiki_fts) AS rk FROM wiki_fts
  WHERE wiki_fts MATCH :q ORDER BY rk LIMIT :k
),
vec AS (
  SELECT path, distance FROM wiki_vec
  WHERE embedding MATCH :embed AND k = :k
)
SELECT path, ... FROM bm25 FULL OUTER JOIN vec USING (path);
```

(The exact shape changes with the `vec0` virtual-table syntax; the point is: one connection, one query.) With LanceDB the BM25 result is in SQLite and the vector result is in Lance — the join happens in Python. That's not wrong, but it's a less natural shape and it precludes future SQL-only call sites (e.g., a Cypher-style traversal that wants to filter on both indexes).

### Scale ceiling

Chimera's near-term retrieval scale:

- `mind/wiki/`: low hundreds of documents today; up to low thousands if chunked-per-paragraph indexing becomes standard.
- ADRs: ~130 today, growing slowly.
- Peer-scoped collections (Phase 3 #1 cross-peer beliefs, when federation protocol lands): bounded by peer count × belief history. Low thousands worst-case.

Brute-force cosine over a few thousand 384-dim float32 vectors is sub-millisecond in C and well under a second in Python. sqlite-vec ships a `vec0` virtual table when we need ANN; LanceDB ships IVF-PQ / HNSW out of the box. Both are sufficient. The Lance ANN edge starts mattering at hundreds of thousands of vectors — that's the trigger for the revisit clause in the ADR.

### Dependency weight

- **sqlite-vec**: one PyPI package; bundles the loadable extension binary. MIT.
- **LanceDB**: `lancedb` + `pyarrow` + `pylance`. Apache 2.0. The pyarrow dep alone is ~50 MB installed.

For a tool whose deployment story is "single Python install", lighter-weight wins.

### Failure mode

When the sqlite-vec extension can't be loaded (stripped Python build, sandboxed environment), our module can still operate by reading the raw BLOB column and computing cosine in Python. Slower, but correct. LanceDB has no equivalent — if the lib doesn't load, the feature is dead.

### Decision

**sqlite-vec.** Adopt when Phase 4 #6.b lands. Revisit if (a) a single peer-scoped collection crosses ~100K documents, (b) operator surveys show sub-second hybrid queries are no longer fast enough, or (c) the `vec0` ANN performance lags Lance's IVF-PQ by more than ~3× on the same corpus.

Status stays **Proposed** until #6.b validates the choice in-situ with a real embedding model.

## Workload assumptions

The recommendation hinges on these holding. If they break, revisit.

1. **Corpus size**: low thousands today, ≤ low tens of thousands plausibly. If chunked-per-paragraph indexing pushes us past 100K vectors, ANN becomes a hard requirement and the brute-force fallback is gone.
2. **Query latency budget**: ≤ 1 second end-to-end for `chimera search --hybrid`. Sub-second is realistic at current scale on commodity hardware.
3. **Embedding dimensionality**: 384–1536 (the range from sentence-transformers `all-MiniLM-L6-v2` through OpenAI `text-embedding-3-small`). Higher dims (4096+) push brute-force memory pressure.
4. **Update frequency**: indexed on demand or at WAKE / ROTATE — not per-keystroke. The brute-force scan tolerates dozens of queries per minute; not thousands.
5. **Single-host deployment**: the index lives next to the agent. Cross-host search (e.g., asking peer X to search their corpus) is a different problem (Phase 3 #2 dialectic API territory).

## Fusion math design notes (deferred to #6.b)

Capturing the reasoning here so #6.b doesn't re-derive it.

### Reciprocal Rank Fusion (RRF)

Cormack, Clarke, Buettcher. *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.

```
score(doc) = Σ_source 1 / (k + rank_source(doc))
```

with `k = 60` canonical. Two properties make it the right pick for us:

1. **No score normalisation needed.** BM25 scores and cosine similarities live in different ranges and distributions. RRF uses *ranks* not scores, so the fusion is invariant under monotonic transforms of either source.
2. **Both-source boost is automatic.** A document that ranks 5 in BM25 and 3 in vector earns `1/65 + 1/63 ≈ 0.0317`. A document that ranks 1 in only BM25 earns `1/61 ≈ 0.0164`. The document seen by both sources outranks the document seen by only one — without a tunable `alpha`.

### Why not weighted score fusion

`final = alpha * normalize(bm25) + (1-alpha) * normalize(cosine)` is the obvious alternative. It introduces three problems:

- `alpha` becomes a per-corpus knob the operator has to tune.
- "Normalize" has to be defined; min-max and z-score both have failure modes (min-max is dominated by outliers; z-score breaks when one source returns < 3 docs).
- The output is sensitive to the normalisation window size.

RRF dodges all three. The only knob is `k`, and the literature says `k=60` is broadly robust.

### Picking `k`

Cormack et al. tested `k` from 1 to 1000 and found `k=60` robust across corpora. Smaller `k` over-weights the top hit; larger `k` flattens the rank-to-score curve. We use `k=60` as a default; nothing in our workload suggests deviating.

### Hybrid behaviour with the flag off

When `CHIMERA_HYBRID_SEARCH=0` (default), `HybridSearcher.search()` is BM25-only — same hits as the existing `search_wiki` from ADR 0080, just wrapped in `HybridHit` dataclasses. This is the load-bearing default; the flag is opt-in for operators experimenting with #6.b before it ships.

## Schema sketch (for #6.b)

```sql
CREATE TABLE wiki_vec(
  path        TEXT PRIMARY KEY,
  dim         INT NOT NULL,
  embedding   BLOB NOT NULL,     -- little-endian float32 packed
  indexed_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- When sqlite-vec is loaded, mirror into a vec0 virtual table:
CREATE VIRTUAL TABLE wiki_vec0 USING vec0(
  path TEXT PRIMARY KEY,
  embedding FLOAT[{dim}]
);
```

`dim` is unknown today because the embedding model is unpicked. #6.b finalises it.

## Named follow-ups for #6.b

In rough priority order. Each is its own chip.

1. **Embedding model decision.** Compare sentence-transformers (`all-MiniLM-L6-v2`, 384-dim, local), Anthropic embeddings (if/when GA), OpenAI `text-embedding-3-small` (1536-dim, hosted). Selection criteria: latency, cost, semantic quality on a small Chimera-corpus eval (10–20 hand-curated query/expected-result pairs).
2. **Wire the embedding model.** `embed_fn` is the contract; #6.b picks one and ships an `embedding.py` module behind a `CHIMERA_EMBEDDING_PROVIDER` env var.
3. **Vector index DDL + writes.** `wiki_vec` table; index on document write / re-write; backfill verb (`chimera search reindex`).
4. **RRF fusion.** Replace the stub `vector_search` with brute-force cosine (Python today, `vec0` when extension loads). Wire into `HybridSearcher.search()` when flag is on.
5. **sqlite-vec extension loader.** Opportunistic; brute-force fallback survives if the extension isn't available.
6. **CLI exposure.** `chimera search --hybrid` flag on the existing `chimera search` verb.
7. **Peer-scoped collections.** Add `peer` column to `wiki_vec` (or split into per-peer tables) so cross-peer queries don't leak.
8. **Dashboard widget.** Surface hit-rate / source-attribution (how often did vector contribute a top-3 hit that BM25 missed).

## References

- Cormack, Clarke, Buettcher. *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
- sqlite-vec: <https://github.com/asg017/sqlite-vec>
- LanceDB: <https://github.com/lancedb/lancedb>
- ADR 0080 — FTS5 substrate.
- ADR 0123 — Phase 4 anchor; pgvector ruled out.
- ADR 0134 — locked-design summary of this note.
