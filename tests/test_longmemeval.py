"""Tests for the LongMemEval adapter (ADR 0135, Proposed).

Scope: cover the adapter shape, ingest/reset/answer cycle, JSONL
I/O, batch runner filters, and the CLI verb's smoke path. Real
benchmark sweeps require the upstream dataset and a judge model;
those land with the integration follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.evals.longmemeval import (
    AnswerResult,
    LongMemEvalAdapter,
    LongMemEvalItem,
    default_results_path,
    load_items,
    run_batch,
    write_results,
)


# ── Item schema ──────────────────────────────────────────────────


def test_item_from_dict_canonical_keys():
    obj = {
        "item_id": "x-1",
        "question": "What pet?",
        "history": [[{"role": "user", "content": "I have a cat."}]],
        "expected_answer": "a cat",
        "category": "single-session-user",
    }
    item = LongMemEvalItem.from_dict(obj)
    assert item.item_id == "x-1"
    assert item.question == "What pet?"
    assert item.category == "single-session-user"
    assert item.expected_answer == "a cat"
    assert len(item.history) == 1


def test_item_from_dict_upstream_aliases():
    """Upstream JSON uses ``haystack_sessions`` + ``answer`` keys."""
    obj = {
        "id": "y-1",
        "question": "?",
        "haystack_sessions": [[{"role": "user", "content": "hi"}]],
        "answer": "ok",
    }
    item = LongMemEvalItem.from_dict(obj)
    assert item.item_id == "y-1"
    assert item.expected_answer == "ok"
    assert len(item.history) == 1


def test_item_from_dict_extras_preserved():
    obj = {
        "item_id": "z", "question": "q", "history": [],
        "category": "abstention", "expected_answer": "",
        "session_count": 50, "extra_field": "kept",
    }
    item = LongMemEvalItem.from_dict(obj)
    assert item.extra == {"session_count": 50, "extra_field": "kept"}


# ── Adapter ──────────────────────────────────────────────────────


@pytest.fixture
def adapter(tmp_path: Path) -> LongMemEvalAdapter:
    return LongMemEvalAdapter(mind_dir=tmp_path / "mind")


def test_ingest_writes_one_file_per_session(adapter, tmp_path):
    item = LongMemEvalItem(
        item_id="t-1", question="?",
        history=[
            [{"role": "user", "content": "hi"}],
            [{"role": "assistant", "content": "hello"}],
        ],
    )
    n = adapter.ingest_history(item)
    assert n == 2
    scratch = tmp_path / "mind" / "wiki" / "longmemeval"
    files = sorted(scratch.glob("*.md"))
    assert len(files) == 2
    body = files[0].read_text()
    assert "Session 0" in body
    assert "user" in body


def test_ingest_skips_empty_turns(adapter, tmp_path):
    item = LongMemEvalItem(
        item_id="t-1", question="?",
        history=[[
            {"role": "user", "content": ""},
            {"role": "user", "content": "real content"},
            {"role": "assistant", "content": "  "},
        ]],
    )
    adapter.ingest_history(item)
    files = list((tmp_path / "mind" / "wiki" / "longmemeval").glob("*.md"))
    body = files[0].read_text()
    assert "real content" in body
    assert body.count("**user**") == 1


def test_reset_truncates_scratch(adapter, tmp_path):
    item = LongMemEvalItem(
        item_id="t-1", question="?",
        history=[[{"role": "user", "content": "hi"}]],
    )
    adapter.ingest_history(item)
    scratch = tmp_path / "mind" / "wiki" / "longmemeval"
    assert len(list(scratch.glob("*.md"))) == 1
    adapter.reset()
    assert list(scratch.glob("*.md")) == []


def test_reset_is_idempotent_on_empty_dir(adapter):
    adapter.reset()  # no scratch dir yet — must not raise
    adapter.reset()


def test_answer_returns_grounded_prompt(adapter, tmp_path):
    item = LongMemEvalItem(
        item_id="t-1", question="What pet?",
        history=[[{"role": "user", "content": "I have a tabby cat."}]],
    )
    adapter.ingest_history(item)
    result = adapter.answer(item)
    assert isinstance(result, AnswerResult)
    assert result.item_id == "t-1"
    assert result.error is None
    assert "What pet?" in result.answer  # the question is in the prompt
    assert result.sources_used  # at least one source consulted


def test_answer_unknown_question_uses_abstention_framing(adapter):
    """No history → dialectic returns the 'no recorded information' framing."""
    item = LongMemEvalItem(item_id="t-1", question="?", history=[])
    result = adapter.answer(item)
    assert result.error is None
    # Abstention framing is what an honest answer looks like with no data.
    assert "no recorded information" in result.answer


def test_answer_swallows_adapter_failure(adapter, monkeypatch):
    """A blown-up dialectic call lands in ``error`` rather than raising."""
    def boom(*args, **kwargs):
        raise RuntimeError("dialectic offline")

    monkeypatch.setattr(
        "chimera.a2a.dialectic.gather_dialectic_context", boom,
    )
    item = LongMemEvalItem(item_id="t-1", question="?", history=[])
    result = adapter.answer(item)
    assert result.error == "dialectic offline"
    assert result.answer == ""


# ── JSONL I/O ────────────────────────────────────────────────────


def test_load_items_empty_when_missing(tmp_path):
    assert load_items(tmp_path / "nope.jsonl") == []


def test_load_items_skips_malformed_lines(tmp_path):
    p = tmp_path / "items.jsonl"
    p.write_text(
        '{"item_id": "ok", "question": "q", "history": []}\n'
        '{garbage line\n'
        '\n'
        '[1, 2, 3]\n'
        '{"item_id": "ok-2", "question": "q2", "history": []}\n'
    )
    items = load_items(p)
    assert [i.item_id for i in items] == ["ok", "ok-2"]


def test_write_results_round_trip(tmp_path):
    results = [
        AnswerResult(
            item_id="a", question="q", answer="x",
            sources_used=["s"], category="c", expected_answer="",
        ),
    ]
    p = tmp_path / "out" / "r.jsonl"
    write_results(results, p)
    assert p.exists()
    payload = json.loads(p.read_text().strip())
    assert payload["item_id"] == "a"
    assert payload["sources_used"] == ["s"]


def test_default_results_path_is_under_mind_evals(tmp_path):
    p = default_results_path(tmp_path / "mind")
    assert p.parent.name == "evals"
    assert p.name.startswith("longmemeval-")
    assert p.suffix == ".jsonl"


# ── Batch runner ─────────────────────────────────────────────────


def _smoke_items() -> list[LongMemEvalItem]:
    return [
        LongMemEvalItem(
            item_id=f"i-{i}", question="?",
            history=[[{"role": "user", "content": f"fact {i}"}]],
            category=cat,
        )
        for i, cat in enumerate(["single-session-user", "multi-session",
                                  "abstention", "temporal-reasoning"])
    ]


def test_run_batch_processes_all_items(adapter):
    results = run_batch(adapter, _smoke_items())
    assert len(results) == 4
    assert [r.item_id for r in results] == ["i-0", "i-1", "i-2", "i-3"]


def test_run_batch_filters_by_subset(adapter):
    results = run_batch(adapter, _smoke_items(), subset="abstention")
    assert len(results) == 1
    assert results[0].category == "abstention"


def test_run_batch_caps_at_limit(adapter):
    results = run_batch(adapter, _smoke_items(), limit=2)
    assert len(results) == 2


def test_run_batch_resets_between_items(adapter, tmp_path):
    """After a batch, the scratch dir is empty (final reset)."""
    run_batch(adapter, _smoke_items())
    scratch = tmp_path / "mind" / "wiki" / "longmemeval"
    if scratch.exists():
        assert list(scratch.glob("*.md")) == []


# ── CLI smoke path ───────────────────────────────────────────────


def test_cli_evals_longmemeval_smoke(tmp_path, monkeypatch, capsys):
    from chimera.cli import main

    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    rc = main(["evals", "longmemeval", "--smoke"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "longmemeval" in out
    # Smoke fixture has 3 items.
    assert "3 item" in out
    # Results file lands under mind/evals/.
    files = list((mind / "evals").glob("longmemeval-*.jsonl"))
    assert len(files) == 1


def test_cli_requires_items_or_smoke(tmp_path, monkeypatch, capsys):
    from chimera.cli import main

    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    rc = main(["evals", "longmemeval"])
    assert rc == 2
    assert "items" in capsys.readouterr().out


def test_cli_evals_longmemeval_help_lists_flags(capsys):
    from chimera.cli import main

    with pytest.raises(SystemExit):
        main(["evals", "longmemeval", "--help"])
    out = capsys.readouterr().out
    assert "--items" in out
    assert "--smoke" in out
    assert "--subset" in out
    assert "--n" in out


# ── ADR 0135 doc presence ─────────────────────────────────────────


def test_adr_0135_present_and_proposed():
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0135-longmemeval-integration.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "Proposed" in body  # status — locks Accepted only after baseline run
    assert "LongMemEval" in body
    assert "0123" in body
