"""Hybrid BM25 + vector search over the wiki corpus (ADR 0134).

Phase 4 #6 of the Honcho-inspired roadmap (ADR 0123). The locked
research decision (ADR 0134) picks **sqlite-vec** over LanceDB as the
vector backend: it reuses Chimera's existing SQLite connection,
preserves the "single binary + SQLite" deployment posture, and
composes naturally with the existing FTS5 BM25 index from ADR 0080.

This module is a **minimal prototype behind ``CHIMERA_HYBRID_SEARCH=1``**:

  * No hard dependency on ``sqlite-vec`` — the module loads the
    extension when available and falls back to a pure-Python
    brute-force cosine search over a raw-bytes BLOB column otherwise.
    Brute-force is fine for the wiki's scale (≤ a few thousand
    documents); the extension matters when peer-scoped collections
    scale into the millions.
  * No baked-in embedding model — the caller passes an ``embed_fn``
    callable. This keeps the module provider-agnostic (matches the
    deriver / peer-cards pattern) and lets follow-ups slot in
    sentence-transformers, OpenAI embeddings, or any local model
    without re-shaping this code.
  * Hybrid fusion via **Reciprocal Rank Fusion (RRF)** — a standard,
    parameter-light combiner that doesn't need score normalisation
    across BM25 vs. cosine.

The flag is **off by default** so existing call sites (the FTS5-only
``search_wiki``) keep working unchanged.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import struct
from dataclasses import dataclass
from typing import Callable, Sequence


logger = logging.getLogger(__name__)


# ── Public types ─────────────────────────────────────────────────


@dataclass(frozen=True)
class HybridHit:
    """One row of the fused result.

    ``score`` is the RRF combined score (higher = better). ``bm25_rank``
    and ``vec_rank`` are the per-source 1-indexed ranks (``None`` when
    the source did not return this document).
    """

    path: str
    score: float
    bm25_rank: int | None
    vec_rank: int | None
    snippet: str = ""


EmbedFn = Callable[[str], Sequence[float]]


# ── Feature flag ─────────────────────────────────────────────────


def hybrid_search_enabled() -> bool:
    """Honor ``CHIMERA_HYBRID_SEARCH`` (default: off, ADR 0134)."""
    raw = os.environ.get("CHIMERA_HYBRID_SEARCH", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# ── Vector storage (raw-blob fallback; sqlite-vec when available) ─


_VEC_TABLE = "wiki_vec"
_VEC_DDL = (
    f"CREATE TABLE IF NOT EXISTS {_VEC_TABLE}("
    " path TEXT PRIMARY KEY, dim INT NOT NULL, embedding BLOB NOT NULL,"
    " indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
)


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Best-effort: load the sqlite-vec extension if installed.

    Returns ``True`` if the extension is now loaded, ``False`` if it
    couldn't be found / loaded. Either way the raw-blob fallback path
    works — the extension is an optimisation, not a correctness gate.
    """
    try:
        import sqlite_vec  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (sqlite3.OperationalError, AttributeError) as exc:
        logger.warning("sqlite-vec load failed: %s; falling back to blob", exc)
        return False


def ensure_vec_index(conn: sqlite3.Connection) -> None:
    """Create the ``wiki_vec`` table if absent. Idempotent."""
    conn.execute(_VEC_DDL)
    conn.commit()


# ── Embedding (de)serialisation ──────────────────────────────────


def _pack_embedding(vec: Sequence[float]) -> bytes:
    """Pack ``vec`` as a little-endian float32 blob (sqlite-vec wire format)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", blob))


def index_document(
    conn: sqlite3.Connection, path: str, embedding: Sequence[float],
) -> None:
    """Upsert one document's embedding."""
    if not embedding:
        return
    ensure_vec_index(conn)
    blob = _pack_embedding(embedding)
    conn.execute(
        f"INSERT INTO {_VEC_TABLE} (path, dim, embedding) "
        f"VALUES (?, ?, ?) "
        f"ON CONFLICT(path) DO UPDATE SET dim=excluded.dim, "
        f"embedding=excluded.embedding, indexed_at=CURRENT_TIMESTAMP",
        (path, len(embedding), blob),
    )
    conn.commit()


# ── Brute-force cosine search ────────────────────────────────────


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def vector_search(
    conn: sqlite3.Connection,
    query_vec: Sequence[float],
    *,
    limit: int = 8,
) -> list[tuple[str, float]]:
    """Return ``[(path, similarity)]`` sorted by descending cosine.

    Uses a brute-force scan today. When the sqlite-vec extension is
    loaded a future PR can swap in a ``vec0`` virtual-table query;
    the interface stays stable.
    """
    if not query_vec:
        return []
    ensure_vec_index(conn)
    rows = conn.execute(
        f"SELECT path, dim, embedding FROM {_VEC_TABLE}"
    ).fetchall()
    scored: list[tuple[str, float]] = []
    for r in rows:
        try:
            vec = _unpack_embedding(r["embedding"], int(r["dim"]))
        except (struct.error, TypeError, ValueError):
            continue
        scored.append((r["path"], _cosine(query_vec, vec)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[: max(1, min(50, int(limit)))]


# ── Hybrid fusion (Reciprocal Rank Fusion) ───────────────────────


_DEFAULT_RRF_K = 60  # canonical RRF constant from Cormack et al.


def _rrf(rank: int, *, k: int = _DEFAULT_RRF_K) -> float:
    """Reciprocal Rank Fusion contribution for a 1-indexed ``rank``."""
    return 1.0 / (k + max(1, rank))


def hybrid_search_wiki(
    conn: sqlite3.Connection,
    query: str,
    *,
    embed_fn: EmbedFn,
    limit: int = 8,
    rrf_k: int = _DEFAULT_RRF_K,
) -> list[HybridHit]:
    """Run BM25 + vector search and combine via RRF.

    ``embed_fn`` is a caller-supplied ``str -> Sequence[float]``
    embedding function. Returning an empty sequence is the documented
    "no vector signal" path — the hybrid degrades to BM25-only.

    Honors :func:`hybrid_search_enabled` — when the flag is off this
    function returns an empty list so call sites that opportunistically
    invoke it don't accidentally pay the embedding cost. Pass the
    flag explicitly in tests via ``monkeypatch.setenv``.
    """
    q = (query or "").strip()
    if not q or not hybrid_search_enabled():
        return []

    # 1. BM25 side — delegate to the existing FTS5 search.
    from .wiki_search import search_wiki

    bm25_hits = search_wiki(conn, q, limit=limit * 2)
    bm25_rank_by_path: dict[str, int] = {
        h.path: i + 1 for i, h in enumerate(bm25_hits)
    }
    snippet_by_path: dict[str, str] = {h.path: h.snippet for h in bm25_hits}

    # 2. Vector side — embed and brute-force search.
    try:
        qvec = list(embed_fn(q))
    except Exception as exc:  # noqa: BLE001 — degrade to BM25 on failure
        logger.warning("hybrid_search: embed_fn failed (%s); BM25 only", exc)
        qvec = []
    vec_hits = vector_search(conn, qvec, limit=limit * 2) if qvec else []
    vec_rank_by_path: dict[str, int] = {
        path: i + 1 for i, (path, _sim) in enumerate(vec_hits)
    }

    # 3. RRF fusion.
    all_paths = set(bm25_rank_by_path) | set(vec_rank_by_path)
    fused: list[HybridHit] = []
    for path in all_paths:
        b = bm25_rank_by_path.get(path)
        v = vec_rank_by_path.get(path)
        score = 0.0
        if b is not None:
            score += _rrf(b, k=rrf_k)
        if v is not None:
            score += _rrf(v, k=rrf_k)
        fused.append(HybridHit(
            path=path, score=score,
            bm25_rank=b, vec_rank=v,
            snippet=snippet_by_path.get(path, ""),
        ))
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused[: max(1, min(50, int(limit)))]


__all__ = [
    "EmbedFn",
    "HybridHit",
    "ensure_vec_index",
    "hybrid_search_enabled",
    "hybrid_search_wiki",
    "index_document",
    "vector_search",
]
