"""Tests for the hybrid-search scaffold (ADR 0134 — Proposed).

Scope per the chip charter: cover the FTS5 BM25 path, the flag
parser, and the stubbed vector path. RRF / cosine / index-round-trip
tests return when Phase 4 #6.b lands.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from chimera.memory.hybrid_search import (
    HybridHit,
    HybridSearcher,
    hybrid_search_enabled,
    vector_search,
)
from chimera.memory.wiki_search import ensure_wiki_index


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_wiki_index(c)
    yield c
    c.close()


def _seed_wiki(conn: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    for path, title, body in rows:
        conn.execute(
            "INSERT INTO wiki_fts(path, title, body) VALUES (?, ?, ?)",
            (path, title, body),
        )
    conn.commit()


# ── Feature flag parser ───────────────────────────────────────────


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


# ── Stubbed vector path ──────────────────────────────────────────


def test_vector_search_is_stub_returns_empty(conn, monkeypatch):
    """Phase 4 #6.b stub: always returns an empty list today."""
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    assert vector_search(conn, query_vec=[1.0, 0.0], limit=5) == []


def test_vector_search_stub_when_flag_off(conn, monkeypatch):
    monkeypatch.delenv("CHIMERA_HYBRID_SEARCH", raising=False)
    assert vector_search(conn, query_vec=None, limit=5) == []


# ── HybridSearcher.search — locked class API ─────────────────────


def test_searcher_empty_query_returns_empty(conn):
    assert HybridSearcher(conn).search("") == []
    assert HybridSearcher(conn).search("   \n  ") == []


def test_searcher_bm25_path_returns_hits(conn, monkeypatch):
    """Flag off → FTS5 BM25 path from ADR 0080 only."""
    monkeypatch.delenv("CHIMERA_HYBRID_SEARCH", raising=False)
    _seed_wiki(conn, [
        ("a.md", "Alpha", "honcho dialectic peer"),
        ("b.md", "Beta", "totally unrelated content"),
    ])
    hits = HybridSearcher(conn).search("honcho")
    assert any(h.path == "a.md" for h in hits)
    top = next(h for h in hits if h.path == "a.md")
    assert top.bm25_rank == 1
    assert top.vec_rank is None  # stub today


def test_searcher_respects_k(conn):
    _seed_wiki(conn, [
        (f"doc-{i}.md", f"T{i}", "honcho dialectic peer extra")
        for i in range(15)
    ])
    hits = HybridSearcher(conn).search("honcho", k=5)
    assert len(hits) == 5


def test_searcher_flag_on_still_bm25_today(conn, monkeypatch):
    """Hybrid flag on touches the stub but result is still BM25-only."""
    monkeypatch.setenv("CHIMERA_HYBRID_SEARCH", "1")
    _seed_wiki(conn, [("a.md", "Alpha", "honcho peer")])
    hits = HybridSearcher(conn).search("honcho")
    assert len(hits) == 1
    assert hits[0].path == "a.md"
    assert hits[0].vec_rank is None  # vector path is stub today


def test_searcher_score_higher_is_better(conn):
    """Score ordering: higher value comes first in the result list."""
    _seed_wiki(conn, [
        ("a.md", "Alpha", "honcho dialectic peer honcho honcho"),
        ("b.md", "Beta", "honcho once"),
    ])
    hits = HybridSearcher(conn).search("honcho")
    assert len(hits) >= 2
    assert hits[0].score >= hits[1].score


# ── HybridHit dataclass shape ────────────────────────────────────


def test_hybrid_hit_dataclass_shape():
    h = HybridHit(path="a", score=0.5, bm25_rank=1, vec_rank=None, snippet="")
    assert h.path == "a"
    assert h.bm25_rank == 1
    assert h.vec_rank is None


# ── ADR + research doc presence ───────────────────────────────────


def test_adr_0134_present_and_proposed():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0134-hybrid-search-eval.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "Proposed" in body  # status; locked to Accepted only after #6.b
    assert "sqlite-vec" in body
    assert "LanceDB" in body
    assert "Phase 4 #6.b" in body or "#6.b" in body


def test_research_note_present():
    note = (
        Path(__file__).parent.parent
        / "mind" / "research" / "hybrid-search-2026-05-24.md"
    )
    assert note.exists()
    body = note.read_text()
    assert "sqlite-vec" in body
    assert "LanceDB" in body
