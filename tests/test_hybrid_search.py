"""Tests for hybrid BM25 + vector search prototype (ADR 0134)."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from chimera.memory.hybrid_search import (
    HybridHit,
    ensure_vec_index,
    hybrid_search_enabled,
    hybrid_search_wiki,
    index_document,
    vector_search,
)
from chimera.memory.wiki_search import ensure_wiki_index


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_wiki_index(c)
    ensure_vec_index(c)
    yield c
    c.close()


def _seed_wiki(conn: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    """Insert ``(path, title, body)`` rows directly into the FTS5 table."""
    for path, title, body in rows:
        conn.execute(
            "INSERT INTO wiki_fts(path, title, body) VALUES (?, ?, ?)",
            (path, title, body),
        )
    conn.commit()


def _seed_embeddings(
    conn: sqlite3.Connection, rows: list[tuple[str, list[float]]],
) -> None:
    for path, vec in rows:
        index_document(conn, path, vec)


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ── Feature flag ──────────────────────────────────────────────────


def test_hybrid_search_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_HYBRID_SEARCH", raising=False)
    assert hybrid_search_enabled() is False


@pytest.mark.parametrize("v,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nope", False),
])
def test_hybrid_search_flag_parses(monkeypatch, v, expected):
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", v)
    assert hybrid_search_enabled() is expected


# ── Vector index round-trip ──────────────────────────────────────


def test_index_and_retrieve_one_document(conn):
    index_document(conn, "doc-a", [1.0, 0.0, 0.0])
    hits = vector_search(conn, [1.0, 0.0, 0.0], limit=5)
    assert hits[0][0] == "doc-a"
    assert hits[0][1] == pytest.approx(1.0)


def test_index_upsert_replaces_existing(conn):
    index_document(conn, "doc-a", [1.0, 0.0, 0.0])
    index_document(conn, "doc-a", [0.0, 1.0, 0.0])
    hits = vector_search(conn, [0.0, 1.0, 0.0], limit=5)
    assert hits[0][0] == "doc-a"
    assert hits[0][1] == pytest.approx(1.0)


def test_index_document_empty_vector_is_noop(conn):
    index_document(conn, "doc-a", [])
    hits = vector_search(conn, [1.0, 0.0], limit=5)
    assert hits == []


def test_vector_search_orders_by_cosine(conn):
    _seed_embeddings(conn, [
        ("a", _unit([1.0, 0.0, 0.0])),
        ("b", _unit([0.9, 0.1, 0.0])),
        ("c", _unit([0.0, 1.0, 0.0])),
    ])
    hits = vector_search(conn, _unit([1.0, 0.0, 0.0]), limit=3)
    assert [h[0] for h in hits] == ["a", "b", "c"]
    assert hits[0][1] > hits[1][1] > hits[2][1]


def test_vector_search_empty_query(conn):
    _seed_embeddings(conn, [("a", [1.0, 0.0])])
    assert vector_search(conn, [], limit=3) == []


def test_vector_search_caps_at_limit(conn):
    _seed_embeddings(conn, [
        (f"doc-{i}", _unit([float(i), 1.0])) for i in range(20)
    ])
    hits = vector_search(conn, _unit([10.0, 1.0]), limit=5)
    assert len(hits) == 5


# ── Hybrid fusion ────────────────────────────────────────────────


def _const_embed(text: str) -> list[float]:
    """Toy embedding: hash-based bag-of-3 vector. Deterministic."""
    v = [0.0, 0.0, 0.0]
    for tok in text.lower().split():
        v[hash(tok) % 3] += 1.0
    return _unit(v)


def test_hybrid_disabled_returns_empty(conn, monkeypatch):
    monkeypatch.delenv("CHIMERA_HYBRID_SEARCH", raising=False)
    _seed_wiki(conn, [("a.md", "Alpha", "honcho dialectic peer")])
    out = hybrid_search_wiki(conn, "honcho", embed_fn=_const_embed)
    assert out == []


def test_hybrid_bm25_only_when_no_vectors(conn, monkeypatch):
    """BM25 hits land in the fused result even when no embeddings exist."""
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [
        ("a.md", "Alpha", "honcho dialectic peer"),
        ("b.md", "Beta", "different content entirely"),
    ])
    out = hybrid_search_wiki(conn, "honcho", embed_fn=_const_embed)
    assert any(h.path == "a.md" for h in out)
    top = [h for h in out if h.path == "a.md"][0]
    assert top.bm25_rank == 1
    assert top.vec_rank is None  # no embedding indexed
    assert top.score > 0.0


def test_hybrid_vector_only_when_no_bm25_match(conn, monkeypatch):
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [("a.md", "Alpha", "totally unrelated text")])
    _seed_embeddings(conn, [("a.md", _const_embed("honcho dialectic"))])
    out = hybrid_search_wiki(
        conn, "honcho", embed_fn=lambda q: _const_embed("honcho dialectic"),
    )
    paths = [h.path for h in out]
    assert "a.md" in paths
    hit = [h for h in out if h.path == "a.md"][0]
    assert hit.vec_rank == 1
    assert hit.bm25_rank is None


def test_hybrid_rrf_boosts_documents_in_both_sources(conn, monkeypatch):
    """A doc returned by BOTH sources scores higher than one in only one."""
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [
        ("both.md", "Both", "honcho dialectic peer"),
        ("bm25.md", "BM25-only", "honcho appears here"),
        ("vec.md",  "Vec-only",  "completely unrelated"),
    ])
    _seed_embeddings(conn, [
        ("both.md", _const_embed("honcho dialectic peer")),
        ("vec.md",  _const_embed("honcho dialectic peer")),
    ])
    out = hybrid_search_wiki(
        conn, "honcho",
        embed_fn=lambda q: _const_embed("honcho dialectic peer"),
    )
    by_path = {h.path: h for h in out}
    assert by_path["both.md"].score > by_path["bm25.md"].score
    assert by_path["both.md"].score > by_path["vec.md"].score
    assert by_path["both.md"].bm25_rank is not None
    assert by_path["both.md"].vec_rank is not None


def test_hybrid_embed_fn_failure_degrades_to_bm25(conn, monkeypatch):
    """An exception in embed_fn must not blow up the call — degrade to BM25."""
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [("a.md", "Alpha", "honcho")])

    def boom(text):
        raise RuntimeError("embedder offline")

    out = hybrid_search_wiki(conn, "honcho", embed_fn=boom)
    assert len(out) == 1
    assert out[0].path == "a.md"
    assert out[0].vec_rank is None


def test_hybrid_empty_query_returns_empty(conn, monkeypatch):
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    out = hybrid_search_wiki(conn, "", embed_fn=_const_embed)
    assert out == []


def test_hybrid_respects_limit(conn, monkeypatch):
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [
        (f"doc-{i}.md", f"T{i}", "honcho dialectic peer extra")
        for i in range(15)
    ])
    out = hybrid_search_wiki(
        conn, "honcho", embed_fn=_const_embed, limit=5,
    )
    assert len(out) == 5


def test_hybrid_hit_dataclass_shape():
    h = HybridHit(path="a", score=0.5, bm25_rank=1, vec_rank=None, snippet="")
    assert h.path == "a"
    assert h.bm25_rank == 1
    assert h.vec_rank is None


# ── ADR 0134 doc presence ─────────────────────────────────────────


def test_adr_0134_present():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0134-hybrid-search-eval.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "sqlite-vec" in body
    assert "LanceDB" in body
    assert "CHIMERA_HYBRID_SEARCH" in body
    assert "Reciprocal Rank Fusion" in body or "RRF" in body
    assert "0080" in body  # references the BM25 FTS5 ADR
