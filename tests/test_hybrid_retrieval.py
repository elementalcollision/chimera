"""Tests for the LongMemEval hybrid retrieval helper (ADR 0142).

Design contract: ``mind/research/t21-hybrid-retrieval-design-2026-05-25.md``.

These tests do NOT call the OpenAI embeddings API. The embed_fn is
mocked with deterministic vectors so the dense path is exercised
without network or spend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.evals.hybrid_retrieval import (
    bm25_rank,
    dense_rank,
    reciprocal_rank_fusion,
    select_top_k_sessions,
)
from chimera.evals.longmemeval import LongMemEvalAdapter, LongMemEvalItem


# ── RRF math ──────────────────────────────────────────────────────


def test_rrf_basic():
    # Item 1 ranks 1st on both lists → should win.
    fused = reciprocal_rank_fusion([[1, 2, 3], [1, 3, 2]], k=60)
    assert fused[0][0] == 1
    # Score = 1/(60+1) + 1/(60+1) = 2/61
    assert fused[0][1] == pytest.approx(2 / 61)


def test_rrf_missing_from_list_contributes_zero():
    # Item 4 only appears in the second list.
    fused = reciprocal_rank_fusion([[1, 2, 3], [4, 1]], k=60)
    scores = dict(fused)
    assert scores[4] == pytest.approx(1 / 61)
    # Item 1 gets first-place in list 1 + second-place in list 2.
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


# ── BM25 ──────────────────────────────────────────────────────────


def test_bm25_finds_matching_session():
    sessions = [
        "user: I love hiking in the alps.",
        "user: My favourite colour is blue.",
        "user: I went to Tokyo last year.",
    ]
    ranks = bm25_rank(sessions, "what colour do they prefer?")
    assert 1 in ranks  # the "colour" session should match
    assert ranks[0] == 1


def test_bm25_empty_query_returns_empty():
    assert bm25_rank(["a b c"], "") == []
    assert bm25_rank(["a b c"], "?!") == []


def test_bm25_no_sessions_returns_empty():
    assert bm25_rank([], "anything") == []


# ── Dense rank ────────────────────────────────────────────────────


def test_dense_rank_orders_by_cosine():
    # Pick vectors where session 2 is collinear with the query.
    vecs = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    q = [1.0, 1.0]
    ranks = dense_rank(vecs, q)
    assert ranks[0] == 2  # collinear ⇒ cosine 1.0


# ── select_top_k_sessions ─────────────────────────────────────────


def test_select_oracle_noop_when_few_sessions():
    sessions = ["s0", "s1", "s2"]
    # Even with no embed_fn and a nonsense question, n <= top_k path
    # short-circuits before any retrieval and returns all indexes.
    out = select_top_k_sessions(sessions, "irrelevant", top_k=8)
    assert out == [0, 1, 2]


def test_select_empty_sessions():
    assert select_top_k_sessions([], "q", top_k=8) == []


def test_select_bm25_only_picks_matching_sessions():
    # 12 sessions; only 2 mention "lacrosse"; top_k=8 forces selection.
    sessions = [f"user: message {i}" for i in range(12)]
    sessions[3] = "user: I play lacrosse on weekends."
    sessions[7] = "user: lacrosse is my favourite sport to play."
    out = select_top_k_sessions(
        sessions, "what sport does the user play?", top_k=8,
    )
    # Selected indexes are returned in chronological order.
    assert out == sorted(out)
    # Both lacrosse sessions must be in the top-k.
    assert 3 in out and 7 in out
    assert len(out) == 8


def test_select_hybrid_with_mocked_embed():
    sessions = [f"session {i}" for i in range(10)]
    # Mock embed: query vec [1,0]; session 5 also [1,0], rest orthogonal.
    def fake_embed(texts):
        out = []
        for i, t in enumerate(texts):
            if i == 0:  # query
                out.append([1.0, 0.0])
            elif texts[i] == sessions[5]:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out

    out = select_top_k_sessions(
        sessions, "no bm25 terms here xyzzy", top_k=3, embed_fn=fake_embed,
    )
    assert out == sorted(out)
    assert 5 in out  # cosine-1.0 session must be selected
    assert len(out) == 3


def test_select_no_signal_returns_first_k_in_order():
    sessions = ["aaa", "bbb", "ccc", "ddd", "eee"]
    # Empty question kills BM25; no embed_fn ⇒ no dense; expect padding path.
    out = select_top_k_sessions(sessions, "", top_k=3)
    assert out == [0, 1, 2]


def test_select_pads_with_unranked_when_bm25_sparse():
    # 10 sessions, only one matches → top_k=4 should backfill 3 more
    # from sessions not yet selected, in original order.
    sessions = [f"user: greeting {i}" for i in range(10)]
    sessions[6] = "user: my cat is named Mochi."
    out = select_top_k_sessions(sessions, "what is the cat's name?", top_k=4)
    assert 6 in out
    assert out == sorted(out)
    assert len(out) == 4


def test_select_recovers_when_embed_fn_raises_timeout():
    """An embed_fn timeout must NOT propagate — fall back to BM25-only.

    Regression for the F2 LoCoMo blocker: a hung Ollama embed call
    used to leave the sweep stuck on a synchronous ``sock_recv`` for
    the full per-call timeout (previously 300 s). The dense-path
    ``except Exception`` already falls back to BM25, but a test
    pins the contract so any future refactor (e.g. moving the
    embedder onto an async path) cannot regress it.
    """
    import httpx

    sessions = [f"user: greeting {i}" for i in range(12)]
    sessions[6] = "user: my cat is named Mochi."

    def raising_embed(texts):
        raise httpx.ReadTimeout("simulated Ollama hang")

    out = select_top_k_sessions(
        sessions, "what is the cat's name?", top_k=4, embed_fn=raising_embed,
    )
    # BM25 still selects the matching session; the timeout did not crash.
    assert 6 in out
    assert len(out) == 4
    assert out == sorted(out)


def test_ollama_embedder_retries_once_on_read_timeout(monkeypatch):
    """OllamaEmbedder retries one time on ReadTimeout before raising.

    Two attempts × bounded timeout is the contract that lets the
    LoCoMo sweep survive intermittent bge-m3 hangs without spending
    the full pre-fix 300 s per stuck call.
    """
    import httpx

    from chimera.evals import hybrid_retrieval as hr

    calls = {"n": 0}

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"embeddings": [[0.1] * 4]}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("first attempt hangs")
            return _FakeResp()

    monkeypatch.setattr(hr.httpx, "Client", _FakeClient)
    emb = hr.OllamaEmbedder(timeout=1.0)
    out = emb(["one"])
    assert out == [[0.1] * 4]
    assert calls["n"] == 2


def test_ollama_embedder_surfaces_after_both_attempts_fail(monkeypatch):
    import httpx

    from chimera.evals import hybrid_retrieval as hr

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, *a, **kw):
            raise httpx.ReadTimeout("always hangs")

    monkeypatch.setattr(hr.httpx, "Client", _FakeClient)
    emb = hr.OllamaEmbedder(timeout=1.0)
    with pytest.raises(httpx.ReadTimeout):
        emb(["one"])


def test_resolve_embed_timeout_honours_env(monkeypatch):
    from chimera.evals.hybrid_retrieval import (
        _DEFAULT_EMBED_TIMEOUT_S,
        _resolve_embed_timeout,
    )

    monkeypatch.delenv("CHIMERA_EMBED_TIMEOUT_S", raising=False)
    assert _resolve_embed_timeout(None) == _DEFAULT_EMBED_TIMEOUT_S
    assert _resolve_embed_timeout(12.5) == 12.5
    monkeypatch.setenv("CHIMERA_EMBED_TIMEOUT_S", "90")
    assert _resolve_embed_timeout(None) == 90.0
    # Explicit arg still wins over env.
    assert _resolve_embed_timeout(5.0) == 5.0
    # Garbage env: falls back to default with a warning, no raise.
    monkeypatch.setenv("CHIMERA_EMBED_TIMEOUT_S", "not-a-float")
    assert _resolve_embed_timeout(None) == _DEFAULT_EMBED_TIMEOUT_S


def test_embed_cache_avoids_re_embedding_identical_text():
    sessions = ["dup text", "dup text", "diff text"] * 4  # 12 sessions
    call_count = {"n": 0}
    def fake_embed(texts):
        call_count["n"] += len(texts)
        # Distinct vec for each unique input keeps dense_rank meaningful.
        return [[hash(t) % 1000 / 1000.0, 1.0] for t in texts]

    cache: dict[str, list[float]] = {}
    select_top_k_sessions(sessions, "query one", top_k=4, embed_fn=fake_embed, embed_cache=cache)
    first = call_count["n"]
    # Second call: same sessions, different query. Query re-embeds; sessions
    # should hit the cache and not be re-embedded.
    select_top_k_sessions(sessions, "query two", top_k=4, embed_fn=fake_embed, embed_cache=cache)
    second = call_count["n"] - first
    # Only the query (1 input) should hit the embedder the second time.
    assert second == 1


# ── Adapter wiring ────────────────────────────────────────────────


def _make_item(n_sessions: int, target_idx: int) -> LongMemEvalItem:
    history = [
        [{"role": "user", "content": f"chitchat message {i}"}]
        for i in range(n_sessions)
    ]
    history[target_idx] = [
        {"role": "user", "content": "my dog's name is Pepper."},
    ]
    return LongMemEvalItem(
        item_id="t-1",
        question="what is the dog's name?",
        history=history,
        expected_answer="Pepper",
        category="single-session-user",
    )


def test_adapter_default_writes_all_sessions(tmp_path: Path):
    adapter = LongMemEvalAdapter(mind_dir=tmp_path)
    item = _make_item(20, target_idx=11)
    adapter.ingest_history(item)
    card = (tmp_path / "peers" / "self.md").read_text()
    # All 20 session headers must be present in default mode.
    for i in range(20):
        assert f"### Session {i}" in card


def test_adapter_hybrid_retrieval_shrinks_card(tmp_path: Path):
    adapter = LongMemEvalAdapter(
        mind_dir=tmp_path,
        hybrid_retrieval=True,
        retrieval_top_k=5,
    )
    item = _make_item(20, target_idx=11)
    adapter.ingest_history(item)
    card = (tmp_path / "peers" / "self.md").read_text()
    # Exactly 5 sessions in the card, and the target must be one of them.
    headers = [line for line in card.splitlines() if line.startswith("### Session")]
    assert len(headers) == 5
    assert "### Session 11" in card


def test_adapter_hybrid_retrieval_oracle_noop(tmp_path: Path):
    """When history is <= top_k, hybrid retrieval is a structural no-op."""
    adapter = LongMemEvalAdapter(
        mind_dir=tmp_path,
        hybrid_retrieval=True,
        retrieval_top_k=8,
    )
    item = _make_item(3, target_idx=1)
    adapter.ingest_history(item)
    card = (tmp_path / "peers" / "self.md").read_text()
    for i in range(3):
        assert f"### Session {i}" in card


def test_adapter_preserves_session_dates_under_hybrid(tmp_path: Path):
    adapter = LongMemEvalAdapter(
        mind_dir=tmp_path,
        hybrid_retrieval=True,
        retrieval_top_k=5,
    )
    item = LongMemEvalItem(
        item_id="t-2",
        question="what is the dog's name?",
        history=[
            [{"role": "user", "content": f"chitchat {i}"}] for i in range(15)
        ],
        session_dates=[f"2026-01-{i+1:02d}" for i in range(15)],
        category="single-session-user",
    )
    # Plant the answer at index 9.
    item.history[9][0]["content"] = "my dog's name is Pepper."
    adapter.ingest_history(item)
    card = (tmp_path / "peers" / "self.md").read_text()
    # The selected sessions must each carry their original date anchor.
    assert "**Session date:** 2026-01-10" in card  # session 9 → 10th day
