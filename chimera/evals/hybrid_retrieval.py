"""Hybrid BM25 + dense retrieval for the LongMemEval adapter (ADR 0142).

Design note (locked, pre-code):
    mind/research/t21-hybrid-retrieval-design-2026-05-25.md

This module is the **measurement-adapter retriever** that the
LongMemEval `_s` long-horizon variant needs to recover from the
−80.80pp cliff documented in chip B1's baseline note. It is
intentionally NOT the canonical Chimera retriever — that scaffold
lives at ``chimera/memory/hybrid_search.py`` (ADR 0134) and is
deferred to Phase 4 #6.b. This module is scoped to LongMemEval and
optimised for per-item, ephemeral indexes over 1–60 sessions.

Public surface:

  * :func:`select_top_k_sessions` — given a question and a list of
    session texts (plus original indexes), return the top-k session
    indexes in original chronological order. Handles oracle no-op
    (``len(sessions) <= k`` → return all indexes unchanged), empty
    inputs, and the BM25-only fallback when ``embed_fn`` is ``None``.
  * :func:`reciprocal_rank_fusion` — pure RRF math; testable in
    isolation.
  * :class:`OpenAIEmbedder` — thin httpx wrapper around
    ``text-embedding-3-small``; lazily instantiated; raises
    ``EmbedderUnavailable`` if ``OPENAI_API_KEY`` is unset.
  * :func:`build_default_embed_fn` — factory that returns an embed
    callable (or ``None`` if the key isn't set, so callers can
    degrade to BM25-only with a logged warning).

Out of scope (per design note):

  * Cross-item caching, surfacing retrieval provenance into
    ``sources_used`` beyond the existing semantics, per-turn
    retrieval, CLI tuning of top-k / k_rrf.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Sequence

import httpx


logger = logging.getLogger(__name__)


# An ``EmbedFn`` takes a list of strings and returns a list of equal
# length of dense float vectors. None means BM25-only mode.
EmbedFn = Callable[[Sequence[str]], list[list[float]]]


# ── RRF math (pure, testable) ─────────────────────────────────────


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[int]],
    *,
    k: int = 60,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion (Cormack et al. 2009).

    Each input list is a ranked sequence of item IDs (best first).
    Returns ``(item_id, fused_score)`` pairs sorted by score
    descending. Items missing from a list contribute 0 from that list
    (equivalent to rank=∞).

    ``k`` is the standard RRF dampener (60 in the literature). Larger
    k flattens the contribution curve; we use the canonical value.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


# ── BM25 via SQLite FTS5 (per-item, in-memory) ────────────────────


_TOKENIZE_RE = re.compile(r"[A-Za-z0-9_]+")


def _fts5_query_from_question(question: str) -> str:
    """Sanitize a free-text question into an FTS5 MATCH query.

    FTS5 MATCH treats most punctuation as syntax. We tokenize to
    word characters, OR-join the terms, and skip stop-word-tiny
    tokens. Empty query → ``""`` (caller treats as "no BM25 signal").
    """
    tokens = _TOKENIZE_RE.findall(question.lower())
    tokens = [t for t in tokens if len(t) > 1]
    if not tokens:
        return ""
    # OR-join; FTS5 wraps each token to avoid being parsed as syntax.
    return " OR ".join(f'"{t}"' for t in tokens)


def bm25_rank(
    session_texts: Sequence[str],
    question: str,
) -> list[int]:
    """Rank session indexes by BM25 against ``question``.

    Returns indexes in best-first order. Sessions with zero overlap
    are omitted (they contribute nothing to RRF either way).
    """
    query = _fts5_query_from_question(question)
    if not query or not session_texts:
        return []
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE s USING fts5(content, tokenize='unicode61')")
        conn.executemany(
            "INSERT INTO s (rowid, content) VALUES (?, ?)",
            [(i + 1, t) for i, t in enumerate(session_texts)],
        )
        try:
            rows = conn.execute(
                "SELECT rowid FROM s WHERE s MATCH ? ORDER BY bm25(s) ASC",
                (query,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("hybrid_retrieval: FTS5 query failed (%s); returning empty BM25 ranks", exc)
            return []
    finally:
        conn.close()
    return [rowid - 1 for (rowid,) in rows]


# ── Dense rank via cosine similarity ──────────────────────────────


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def dense_rank(
    session_vecs: Sequence[Sequence[float]],
    query_vec: Sequence[float],
) -> list[int]:
    """Rank session indexes by cosine similarity to ``query_vec``.

    Returns indexes in best-first order. All sessions are included
    (cosine has no natural cutoff at this layer; RRF handles fusion).
    """
    if not session_vecs:
        return []
    sims = [(i, _cosine(v, query_vec)) for i, v in enumerate(session_vecs)]
    sims.sort(key=lambda iv: iv[1], reverse=True)
    return [i for i, _ in sims]


# ── Top-level selector ────────────────────────────────────────────


@dataclass(frozen=True)
class RetrievalDebug:
    """Optional debug surface for tests + post-hoc analysis."""

    n_sessions: int
    top_k: int
    used_dense: bool
    bm25_ranks: list[int]
    dense_ranks: list[int]
    fused: list[tuple[int, float]]
    selected: list[int]


def select_top_k_sessions(
    session_texts: Sequence[str],
    question: str,
    *,
    top_k: int = 8,
    embed_fn: EmbedFn | None = None,
    embed_cache: dict[str, list[float]] | None = None,
    rrf_k: int = 60,
    debug_out: list[RetrievalDebug] | None = None,
) -> list[int]:
    """Select top-k session indexes for ``question``.

    Returns indexes in **original chronological order** (sorted ascending),
    NOT in score order — the LongMemEval self-card must preserve
    chronological session ordering so the temporal-grounding fix from
    PR #69 still holds.

    Oracle no-op: if ``len(session_texts) <= top_k``, returns
    ``list(range(len(session_texts)))`` without invoking BM25 or
    embeddings. This is the parameter-free path that prevents any
    regression on the oracle variant (1–3 sessions per item).

    BM25-only fallback: if ``embed_fn`` is ``None``, the dense rank is
    empty and RRF reduces to BM25. The caller is expected to log a
    warning at the surface where the fallback was chosen (we don't
    re-log here on every call).
    """
    n = len(session_texts)
    if n == 0:
        return []
    if n <= top_k:
        # Oracle / small-haystack path: no retrieval needed.
        return list(range(n))

    bm25 = bm25_rank(session_texts, question)

    dense: list[int] = []
    used_dense = False
    if embed_fn is not None and question.strip():
        try:
            to_embed: list[str] = [question]
            need_idx: list[int] = []
            need_text: list[str] = []
            session_keys = [_hash(t) for t in session_texts]
            cache = embed_cache if embed_cache is not None else {}
            for i, (t, key) in enumerate(zip(session_texts, session_keys)):
                if key not in cache:
                    need_idx.append(i)
                    need_text.append(t)
            if need_text:
                to_embed.extend(need_text)
            vecs = embed_fn(to_embed)
            if len(vecs) != len(to_embed):
                raise ValueError(
                    f"embed_fn returned {len(vecs)} vectors for {len(to_embed)} inputs"
                )
            query_vec = vecs[0]
            for j, i in enumerate(need_idx):
                cache[session_keys[i]] = vecs[1 + j]
            session_vecs = [cache[k] for k in session_keys]
            dense = dense_rank(session_vecs, query_vec)
            used_dense = True
        except Exception as exc:  # noqa: BLE001 — measurement adapter, never break the sweep
            logger.warning(
                "hybrid_retrieval: dense path failed (%s); falling back to BM25-only",
                exc,
            )
            dense = []
            used_dense = False

    if not bm25 and not dense:
        # No signal from either path → return the first ``top_k`` in
        # original order. Honest default; the alternative (random k)
        # adds noise without information.
        selected = list(range(top_k))
        if debug_out is not None:
            debug_out.append(RetrievalDebug(
                n_sessions=n, top_k=top_k, used_dense=used_dense,
                bm25_ranks=[], dense_ranks=[], fused=[], selected=selected,
            ))
        return selected

    fused = reciprocal_rank_fusion(
        [r for r in (bm25, dense) if r],
        k=rrf_k,
    )
    top_ids = [item_id for item_id, _ in fused[:top_k]]
    if len(top_ids) < top_k:
        # Pad from sessions not yet selected, in original order.
        seen = set(top_ids)
        for i in range(n):
            if i not in seen:
                top_ids.append(i)
                seen.add(i)
                if len(top_ids) >= top_k:
                    break
    selected = sorted(top_ids)
    if debug_out is not None:
        debug_out.append(RetrievalDebug(
            n_sessions=n, top_k=top_k, used_dense=used_dense,
            bm25_ranks=list(bm25), dense_ranks=list(dense),
            fused=list(fused), selected=selected,
        ))
    return selected


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ── OpenAI embedder ───────────────────────────────────────────────


class EmbedderUnavailable(RuntimeError):
    """Raised when an OpenAI embedder is requested without an API key."""


_DEFAULT_OLLAMA_URL = "http://ollama.deploy.orb.local"
_DEFAULT_EMBED_MODEL = "bge-m3:latest"
_VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings"
_VOYAGE_DEFAULT_MODEL = "voyage-3-lite"


class VoyageEmbedder:
    """Thin httpx wrapper around the Voyage AI embeddings endpoint.

    Voyage's API is OpenAI-shaped: POST /v1/embeddings with
    {model, input: [str, ...]} returns {data: [{embedding: [...]}, ...]}.
    Batched per call (we send query + all sessions in one request) to
    keep per-item latency well under the 17 s/item LongMemEval budget.

    Voyage's pricing for voyage-3-lite is ~$0.02/1M tokens at the time
    of writing; an `_s` 500-item sweep at ~50 sessions × ~2K tokens =
    ~50M tokens total ⇒ ~$1.
    """

    def __init__(
        self,
        *,
        model: str = _VOYAGE_DEFAULT_MODEL,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise EmbedderUnavailable("VOYAGE_API_KEY not set")
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self._model = model
        self._timeout = timeout

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # voyage-3-lite caps inputs at ~32K tokens; truncate to 8 KB
        # chars (~2K tokens) for retrieval signal headroom + safety.
        clipped = [t[:8_000] for t in texts]
        body = {"model": self._model, "input": clipped}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(_VOYAGE_EMBED_URL, headers=self._headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Voyage embeddings HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
        return [row["embedding"] for row in data["data"]]


class OllamaEmbedder:
    """Thin httpx wrapper around an Ollama ``/api/embed`` endpoint.

    Batched: a single call embeds a list of strings. We use it that
    way (one call per item, batching query + all sessions) so the
    per-item latency stays well under the 17 s/item budget.

    The default URL points at the operator's local Ollama instance
    (``ollama.deploy.orb.local``) which hosts ``bge-m3:latest`` (1024-d).
    Override via ``CHIMERA_OLLAMA_URL`` / ``CHIMERA_EMBED_MODEL``.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._url = (
            url or os.environ.get("CHIMERA_OLLAMA_URL") or _DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self._model = (
            model or os.environ.get("CHIMERA_EMBED_MODEL") or _DEFAULT_EMBED_MODEL
        )
        self._timeout = timeout

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # bge-m3 has an 8K-token context, but throughput collapses on
        # long inputs (observed 40+ s for batches of 50 × ~12 KB).
        # 8 KB chars (~2K tokens) is plenty for session-level retrieval
        # signal — FTS5 covers exact-match recall on the full body, so
        # the dense path only needs the topic vector.
        clipped = [t[:8_000] for t in texts]
        body = {"model": self._model, "input": clipped}
        endpoint = f"{self._url}/api/embed"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(endpoint, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Ollama embeddings HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
        embeds = data.get("embeddings")
        if not isinstance(embeds, list) or len(embeds) != len(clipped):
            raise RuntimeError(
                f"Ollama embeddings: unexpected payload shape "
                f"(got {len(embeds) if isinstance(embeds, list) else type(embeds)} for {len(clipped)} inputs)"
            )
        return embeds


def build_default_embed_fn() -> EmbedFn | None:
    """Return an embed callable, or None if no backend is available.

    Preference order (highest quality / lowest local-load first):

    1. ``VOYAGE_API_KEY`` set → :class:`VoyageEmbedder` (voyage-3-lite,
       cloud, well-tuned for retrieval, ~$0.02/1M tokens).
    2. Local Ollama at ``CHIMERA_OLLAMA_URL`` reachable →
       :class:`OllamaEmbedder` (bge-m3 default, free but bottlenecks
       on large LongMemEval `_s` batches per ADR 0142 design note
       §"Failure-mode register").
    3. Otherwise → ``None`` (caller falls back to BM25-only with a
       logged warning at the surface).
    """
    if os.environ.get("VOYAGE_API_KEY"):
        try:
            emb = VoyageEmbedder()
            emb(["x"])  # liveness
            return emb
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hybrid_retrieval: Voyage embedder failed liveness (%s); "
                "trying Ollama next",
                exc,
            )
    try:
        emb = OllamaEmbedder()
        emb(["x"])  # liveness
        return emb
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "hybrid_retrieval: no embedder available (%s); "
            "callers will fall back to BM25-only",
            exc,
        )
        return None


__all__ = [
    "EmbedFn",
    "EmbedderUnavailable",
    "OllamaEmbedder",
    "VoyageEmbedder",
    "RetrievalDebug",
    "bm25_rank",
    "build_default_embed_fn",
    "dense_rank",
    "reciprocal_rank_fusion",
    "select_top_k_sessions",
]
