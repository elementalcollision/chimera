# ADR 0134 — Hybrid BM25 + vector search vendor decision (Phase 4 / item #6)

**Status**: **Proposed** (recommendation pending real-embedding integration in Phase 4 #6.b)

**Relationship**: Phase 4 item #6 from [ADR 0123](./0123-honcho-inspired-enhancements.md): *"Hybrid BM25 + vector search over peer-scoped collections — use sqlite-vec or LanceDB, NOT pgvector. `chimera/wiki_search.py`."* Builds on the FTS5 BM25 index from [ADR 0080](./0080-wiki-fts-search.md).

The full vendor evaluation, workload assumptions, and benchmark notes live in [`mind/research/hybrid-search-2026-05-24.md`](../../mind/research/hybrid-search-2026-05-24.md). This ADR captures the locked-design only.

## Recommendation

**Adopt sqlite-vec as the vector backend** when Phase 4 #6.b lands. Reasoning summary (full analysis in the research note):

1. Reuses Chimera's existing SQLite connection — no separate engine, no new storage tree.
2. Hybrid composition is natural: BM25 (FTS5) lives in the same connection as the vector index.
3. Brute-force is fine at current scale; `vec0` virtual table is available when peer-scoped collections cross ~100K vectors.
4. Graceful failure mode: module degrades to brute-force pure-Python cosine over a raw-bytes BLOB if the extension is absent.
5. Lower dep weight than LanceDB (one PyPI package vs. three).

Status stays **Proposed** until Phase 4 #6.b makes the real-embedding integration and validates the choice in-situ.

## Locked design (this PR — scaffold only)

[`chimera/memory/hybrid_search.py`](../../chimera/memory/hybrid_search.py) exposes:

- **`HybridSearcher`** class — instantiated with a SQLite connection; `search(query, *, k=10) -> list[HybridHit]` is the contract.
- **`HybridHit`** dataclass — `(path, score, bm25_rank, vec_rank, snippet)`. Field shape is stable for #6.b.
- **`vector_search(conn, query_vec, *, limit)`** — **stub** that returns `[]` and logs a one-liner when the hybrid flag is set. Filled in by #6.b.
- **`hybrid_search_enabled()`** — honours `CHIMERA_HYBRID_SEARCH=1` (default off).

Today the class delegates to the FTS5 BM25 path from ADR 0080 and wraps each hit. With the flag on, the searcher touches the vector stub so operators see the deferred-work log line; the returned hits remain BM25-only until #6.b ships.

## Deferred to #6.b

The following live in the research note now, and land in code with the real-embedding integration:

- **RRF fusion math.** Reciprocal Rank Fusion (Cormack et al., SIGIR 2009) with the canonical `k=60`. Picked over score-weighted fusion to sidestep BM25-vs-cosine score normalisation. Both-source boost (docs appearing in both BM25 and vector results outscore single-source docs) is a property of the fusion, not a separate knob.
- **Vector index DDL.** `wiki_vec(path PK, dim, embedding BLOB, indexed_at)`. Schema is sketched in the research note; finalised in #6.b once the embedding-model decision picks a `dim`.
- **Embedding-function contract.** Caller-supplied `embed_fn: str -> Sequence[float]`. Concrete model selection (sentence-transformers vs. Anthropic vs. OpenAI embeddings vs. local Ollama) is the core question #6.b answers.
- **sqlite-vec extension load path.** Opportunistic with brute-force fallback; the load semantics are sketched in the research note.
- **Brute-force cosine** over the BLOB column for installations without the extension.

These decisions stay out of the locked surface until #6.b can answer "which model, which dim, which storage shape" — locking them now would freeze the API before the embedding decision constrains it.

## Consequences

### Positive

- The class name `HybridSearcher` is the contract: consumers can depend on it today and pick up RRF-fused hits transparently when #6.b lands.
- The vendor recommendation is captured in writing with the full analysis archived in `mind/research/` for future contributors to audit.
- Default-off flag means zero impact on existing FTS5 call sites.

### Negative

- Two-step landing (scaffold now, integration later) adds a coordination cost between this chip and #6.b.
- The `Proposed` status means callers shouldn't load-bear on the *vector* path yet — only the FTS5 path is `Accepted`-quality today.

## Out of scope (this PR)

- Anything described under "Deferred to #6.b" above.
- A concrete embedding model.
- CLI / dashboard exposure (`chimera search --hybrid`).
- Peer-scoped collections.
- Phase 4 #8 (LongMemEval / LoCoMo eval harness integration) — a separate research ADR.

## References

- [`mind/research/hybrid-search-2026-05-24.md`](../../mind/research/hybrid-search-2026-05-24.md) — long-form vendor evaluation + workload assumptions + RRF design notes.
- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 4 anchor; pgvector ruled out.
- [ADR 0080 — mind/wiki FTS5 search](./0080-wiki-fts-search.md) — BM25 substrate.
- [`chimera/memory/hybrid_search.py`](../../chimera/memory/hybrid_search.py), [`chimera/memory/wiki_search.py`](../../chimera/memory/wiki_search.py).
