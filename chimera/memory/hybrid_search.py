"""Hybrid BM25 + vector search scaffold (ADR 0134 — Proposed).

Phase 4 #6 of the Honcho-inspired roadmap (ADR 0123). This is a
**research-first scaffold**: it locks the public class shape
(`HybridSearcher.search`) and the SQLite FTS5 BM25 path, and leaves
the vector half as a stub. The RRF fusion, the vector index schema,
and the embed-fn contract land in Phase 4 #6.b alongside the
real-embedding-model integration — see ADR 0134 §"Deferred to #6.b".

Why scaffold-only:

  The vendor recommendation (sqlite-vec over LanceDB) is Proposed
  pending an embedding-model decision. Locking the surface now would
  freeze the API before #6.b can answer "which model, which dim,
  which storage shape". The class exists today so consumers can
  depend on the name; the vector path is documented stub.

Public surface:

  * :class:`HybridSearcher` — instantiated with a SQLite connection.
    ``search(query, k=10)`` returns FTS5 hits today; will return RRF-
    fused hits when #6.b lands. The signature is the contract.
  * :func:`hybrid_search_enabled` — honours
    ``CHIMERA_HYBRID_SEARCH=1``. The flag changes nothing today
    (vector path stubs to empty); future #6.b enables the real path.

Out of scope (deferred to #6.b):

  * RRF fusion math.
  * Vector index DDL (``wiki_vec`` table).
  * Brute-force cosine search.
  * Embedding-function contract.
  * sqlite-vec extension loading.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass


logger = logging.getLogger(__name__)


# ── Public types ─────────────────────────────────────────────────


@dataclass(frozen=True)
class HybridHit:
    """One hit from :meth:`HybridSearcher.search`.

    Today: ``bm25_rank`` is populated from the FTS5 result; ``vec_rank``
    is always ``None``. Field shape stays stable for #6.b.
    """

    path: str
    score: float
    bm25_rank: int | None
    vec_rank: int | None
    snippet: str = ""


# ── Feature flag ─────────────────────────────────────────────────


def hybrid_search_enabled() -> bool:
    """Honor ``CHIMERA_HYBRID_SEARCH`` (default: off, ADR 0134)."""
    raw = os.environ.get("CHIMERA_HYBRID_SEARCH", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# ── Stub: vector search ──────────────────────────────────────────


def vector_search(
    conn: sqlite3.Connection,
    query_vec,
    *,
    limit: int = 8,
) -> list[tuple[str, float]]:
    """Stub — returns ``[]``. Real implementation lands in Phase 4 #6.b.

    Kept as a public symbol so #6.b can fill it in without changing
    the import surface. Logs a one-liner when the hybrid flag is set
    so operators see why the path is empty.
    """
    if hybrid_search_enabled():
        logger.info(
            "hybrid_search: vector_search is a Phase 4 #6.b stub; "
            "returning [] — see ADR 0134.",
        )
    return []


# ── HybridSearcher class ─────────────────────────────────────────


class HybridSearcher:
    """The locked public surface for Phase 4 #6.

    Today: ``search(query, k)`` delegates to the FTS5 BM25 path from
    ADR 0080 and wraps the result in :class:`HybridHit`. When #6.b
    lands, the same call signature returns RRF-fused BM25+vector
    hits without consumers having to change their code.

    The class is the contract. Consumers should depend on it.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def search(self, query: str, *, k: int = 10) -> list[HybridHit]:
        """Return up to ``k`` hits for ``query``.

        Behavior contract:

          * Empty query → empty list.
          * Hybrid flag off → BM25-only (FTS5 path from ADR 0080).
          * Hybrid flag on → BM25 + (stub vector path) today; RRF-
            fused result when #6.b ships. The fusion math is
            documented in ADR 0134 §"Deferred to #6.b".
        """
        q = (query or "").strip()
        if not q:
            return []

        from .wiki_search import search_wiki

        bm25_hits = search_wiki(self._conn, q, limit=k)
        out: list[HybridHit] = []
        for i, h in enumerate(bm25_hits):
            out.append(HybridHit(
                path=h.path,
                # FTS5 BM25 is negative-better; invert so higher == better.
                score=-float(h.rank),
                bm25_rank=i + 1,
                vec_rank=None,
                snippet=h.snippet,
            ))

        if hybrid_search_enabled():
            # Touch the stub so the "Phase 4 #6.b" log line fires when
            # operators exercise the flag — keeps the deferred-work
            # signal visible without changing output.
            _ = vector_search(self._conn, query_vec=None, limit=k)

        return out


__all__ = [
    "HybridHit",
    "HybridSearcher",
    "hybrid_search_enabled",
    "vector_search",
]
