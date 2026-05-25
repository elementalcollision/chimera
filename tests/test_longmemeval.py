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


def test_item_from_dict_extracts_dates():
    """Upstream LongMemEval ships question_date + haystack_dates parallel
    to haystack_sessions. Both must land on the dataclass, not in extra,
    so the adapter can surface them as grounding (chip: timestamp grounding 2026-05-25)."""
    obj = {
        "question_id": "tr-1",
        "question_type": "temporal-reasoning",
        "question": "How many days ago?",
        "haystack_sessions": [
            [{"role": "user", "content": "first"}],
            [{"role": "user", "content": "second"}],
        ],
        "answer": "4 days ago",
        "question_date": "2023/04/10 (Mon) 23:07",
        "haystack_dates": ["2023/04/06 (Thu) 10:00", "2023/04/08 (Sat) 14:00"],
    }
    item = LongMemEvalItem.from_dict(obj)
    assert item.question_date == "2023/04/10 (Mon) 23:07"
    assert item.session_dates == ["2023/04/06 (Thu) 10:00", "2023/04/08 (Sat) 14:00"]
    assert "question_date" not in item.extra
    assert "haystack_dates" not in item.extra


def test_item_from_dict_dates_default_empty():
    """No-date items still load — defensive fallback for unit-test fixtures."""
    item = LongMemEvalItem.from_dict({"item_id": "x", "question": "?", "history": []})
    assert item.question_date == ""
    assert item.session_dates == []


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


def test_ingest_writes_today_date_anchor(adapter, tmp_path):
    """question_date lands at the top of the self peer card so the
    answerer has an absolute 'now' for temporal arithmetic
    (chip: timestamp grounding 2026-05-25)."""
    item = LongMemEvalItem(
        item_id="tr-1", question="How many days ago?",
        history=[[{"role": "user", "content": "I bought a car today"}]],
        question_date="2023/04/10 (Mon) 23:07",
        session_dates=["2023/04/06 (Thu) 10:00"],
    )
    adapter.ingest_history(item)
    self_card = (tmp_path / "mind" / "peers" / "self.md").read_text()
    assert "**Today's date:** 2023/04/10 (Mon) 23:07" in self_card
    # Anchor must appear above the History section so the model reads it first.
    assert self_card.index("Today's date:") < self_card.index("## History")


def test_ingest_writes_per_session_date_headers(adapter, tmp_path):
    """Each session block carries its send-timestamp on both the self
    card and the per-session scratch file."""
    item = LongMemEvalItem(
        item_id="tr-2", question="?",
        history=[
            [{"role": "user", "content": "session zero"}],
            [{"role": "user", "content": "session one"}],
        ],
        question_date="2023/04/10 (Mon) 23:07",
        session_dates=["2023/04/06 (Thu) 10:00", "2023/04/08 (Sat) 14:00"],
    )
    adapter.ingest_history(item)
    self_card = (tmp_path / "mind" / "peers" / "self.md").read_text()
    assert "**Session date:** 2023/04/06 (Thu) 10:00" in self_card
    assert "**Session date:** 2023/04/08 (Sat) 14:00" in self_card
    # Scratch files also carry the timestamp for future hybrid retrieval.
    scratch_dir = tmp_path / "mind" / "wiki" / "longmemeval"
    bodies = [p.read_text() for p in sorted(scratch_dir.glob("*.md"))]
    assert "**Session date:** 2023/04/06 (Thu) 10:00" in bodies[0]
    assert "**Session date:** 2023/04/08 (Sat) 14:00" in bodies[1]


def test_ingest_without_dates_omits_headers(adapter, tmp_path):
    """Defensive: items without date metadata ingest cleanly with no
    Today's-date / Session-date lines (preserves all pre-chip behaviour)."""
    item = LongMemEvalItem(
        item_id="t-nodates", question="?",
        history=[[{"role": "user", "content": "hi"}]],
    )
    adapter.ingest_history(item)
    self_card = (tmp_path / "mind" / "peers" / "self.md").read_text()
    assert "Today's date" not in self_card
    assert "Session date" not in self_card


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


# ── --answer / answer_fn path ─────────────────────────────────────


def test_answer_with_answer_fn_returns_hypothesis(adapter):
    """When answer_fn is provided, hypothesis + question_id populate."""
    item = LongMemEvalItem(
        item_id="t-ans", question="What pet?",
        history=[[{"role": "user", "content": "I have a tabby cat."}]],
    )
    adapter.ingest_history(item)

    seen_prompts: list[str] = []

    def fake_answer(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "A tabby cat."

    result = adapter.answer(item, answer_fn=fake_answer)
    assert result.hypothesis == "A tabby cat."
    assert result.answer == "A tabby cat."  # answer aliases hypothesis
    assert result.question_id == "t-ans"
    assert len(seen_prompts) == 1
    assert "What pet?" in seen_prompts[0]


def test_answer_without_answer_fn_keeps_prompt(adapter):
    """Default path (no answer_fn) keeps the prompt-only behaviour."""
    item = LongMemEvalItem(
        item_id="t-prompt", question="?",
        history=[[{"role": "user", "content": "hi"}]],
    )
    adapter.ingest_history(item)
    result = adapter.answer(item)
    assert result.hypothesis is None
    assert result.question_id is None
    # answer holds the assembled dialectic prompt
    assert "?" in result.answer


def test_run_batch_threads_answer_fn(adapter):
    items = [
        LongMemEvalItem(
            item_id=f"b-{i}", question="q",
            history=[[{"role": "user", "content": "x"}]],
            category="single-session-user",
        )
        for i in range(3)
    ]

    calls = {"n": 0}

    def stub(prompt: str) -> str:
        calls["n"] += 1
        return f"answer-{calls['n']}"

    results = run_batch(adapter, items, answer_fn=stub)
    assert calls["n"] == 3
    assert all(r.hypothesis and r.hypothesis.startswith("answer-") for r in results)
    assert all(r.question_id is not None for r in results)


def test_run_batch_per_category_limit(adapter):
    items = [
        LongMemEvalItem(
            item_id=f"i-{i}", question="?",
            history=[[{"role": "user", "content": "x"}]],
            category=cat,
        )
        for i, cat in enumerate(
            ["a", "a", "a", "b", "b", "c", "c", "c", "c"]
        )
    ]
    results = run_batch(adapter, items, per_category_limit=2)
    cats = [r.category for r in results]
    assert cats.count("a") == 2
    assert cats.count("b") == 2
    assert cats.count("c") == 2


def test_run_batch_per_category_limit_combines_with_subset(adapter):
    items = [
        LongMemEvalItem(
            item_id=f"i-{i}", question="?",
            history=[[{"role": "user", "content": "x"}]],
            category=cat,
        )
        for i, cat in enumerate(
            ["abstention", "abstention", "abstention", "temporal-reasoning"]
        )
    ]
    results = run_batch(
        adapter, items, subset="abstention", per_category_limit=2,
    )
    assert len(results) == 2
    assert all(r.category == "abstention" for r in results)


# ── summarize_results / format_summary_table (runbook helpers) ───


def _write_graded(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_summarize_results_per_category_accuracy(tmp_path):
    from chimera.evals.longmemeval import summarize_results

    p = tmp_path / "graded.jsonl"
    _write_graded(p, [
        {"category": "single-session-user", "is_correct": True},
        {"category": "single-session-user", "is_correct": False},
        {"category": "single-session-user", "is_correct": True},
        {"category": "multi-session", "is_correct": True},
        {"category": "abstention", "is_correct": False},
    ])
    summary = summarize_results(p)
    assert summary["single-session-user"]["total"] == 3
    assert summary["single-session-user"]["correct"] == 2
    assert summary["single-session-user"]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["_overall"]["total"] == 5
    assert summary["_overall"]["correct"] == 3
    assert summary["_overall"]["accuracy"] == pytest.approx(0.6, abs=1e-4)


def test_summarize_results_missing_file_returns_empty(tmp_path):
    from chimera.evals.longmemeval import summarize_results
    assert summarize_results(tmp_path / "nope.jsonl") == {}


def test_summarize_results_skips_malformed_lines(tmp_path):
    from chimera.evals.longmemeval import summarize_results

    p = tmp_path / "graded.jsonl"
    p.write_text(
        '{"category": "a", "is_correct": true}\n'
        '{garbage\n'
        '\n'
        '[1, 2, 3]\n'
        '{"category": "a", "is_correct": false}\n'
    )
    summary = summarize_results(p)
    assert summary["a"]["total"] == 2
    assert summary["a"]["correct"] == 1


def test_summarize_results_uncategorised_bucket(tmp_path):
    from chimera.evals.longmemeval import summarize_results
    p = tmp_path / "graded.jsonl"
    _write_graded(p, [{"is_correct": True}, {"is_correct": False}])
    summary = summarize_results(p)
    assert "(uncategorised)" in summary
    assert summary["(uncategorised)"]["total"] == 2


def test_summarize_results_custom_correctness_field(tmp_path):
    """Operator may use a different upstream key (e.g. 'judged_correct')."""
    from chimera.evals.longmemeval import summarize_results
    p = tmp_path / "graded.jsonl"
    _write_graded(p, [
        {"category": "x", "judged_correct": True},
        {"category": "x", "judged_correct": False},
    ])
    summary = summarize_results(p, correctness_field="judged_correct")
    assert summary["x"]["correct"] == 1


def test_summarize_results_ungraded_items_pull_accuracy_down(tmp_path):
    """An item missing the correctness field counts toward total but not correct."""
    from chimera.evals.longmemeval import summarize_results
    p = tmp_path / "graded.jsonl"
    _write_graded(p, [
        {"category": "x", "is_correct": True},
        {"category": "x"},  # ungraded
    ])
    summary = summarize_results(p)
    assert summary["x"]["total"] == 2
    assert summary["x"]["correct"] == 1
    assert summary["x"]["accuracy"] == pytest.approx(0.5, abs=1e-4)


def test_format_summary_table_includes_overall_row():
    from chimera.evals.longmemeval import format_summary_table
    table = format_summary_table({
        "a": {"total": 2, "correct": 1, "accuracy": 0.5},
        "_overall": {"total": 2, "correct": 1, "accuracy": 0.5},
    })
    assert "| Category |" in table
    assert "| a | 2 | 1 | 50.00% |" in table
    assert "**overall**" in table


def test_format_summary_table_empty():
    from chimera.evals.longmemeval import format_summary_table
    assert "no results" in format_summary_table({})


# ── Baseline note presence ────────────────────────────────────────


def test_baseline_note_template_present():
    note = (
        Path(__file__).parent.parent
        / "mind" / "research" / "longmemeval-baseline-2026-05-24.md"
    )
    assert note.exists()
    body = note.read_text()
    assert "LongMemEval" in body
    # Promotion checklist landmarks.
    assert "Promotion" in body or "promote" in body.lower()
    assert "0135" in body
    # Operator commands.
    assert "chimera evals longmemeval" in body


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


# ── Chip T1.1 — --answer-max-tokens budget plumbing ───────────────


def test_openrouter_answer_fn_default_max_tokens_is_2048(monkeypatch):
    """Chip T1.1: default budget is 2048 (raised from 512 to recover the
    6/30 reasoning-token-exhaustion empties surfaced in the smoke
    baseline). The CLI default and the function default agree."""
    from chimera import cli as _cli

    captured: dict = {}

    class _FakeResponse:
        text = "ok"

    class _FakeProvider:
        async def complete_with_tools(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        "chimera.providers.OpenRouterProvider",
        lambda: _FakeProvider(),
    )

    fn = _cli._build_openrouter_answer_fn("openai/test-model")
    out = fn("hello")
    assert out == "ok"
    assert captured["max_tokens"] == 2048, (
        f"default max_tokens should be 2048 (Chip T1.1), got {captured['max_tokens']}"
    )


def test_openrouter_answer_fn_explicit_max_tokens_passes_through(monkeypatch):
    """Chip T1.1: caller-supplied --answer-max-tokens N is plumbed
    through the function signature into the provider call verbatim."""
    from chimera import cli as _cli

    captured: dict = {}

    class _FakeResponse:
        text = "ok"

    class _FakeProvider:
        async def complete_with_tools(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        "chimera.providers.OpenRouterProvider",
        lambda: _FakeProvider(),
    )

    fn = _cli._build_openrouter_answer_fn("openai/test-model", max_tokens=4096)
    fn("hello")
    assert captured["max_tokens"] == 4096


def test_cli_answer_max_tokens_flag_present_with_default_2048():
    """Chip T1.1: --answer-max-tokens is a registered argparse flag
    with default 2048. Parsing without it yields 2048; explicit value
    is preserved."""
    from chimera import cli as _cli

    parser = _cli._build_parser()
    ns_default = parser.parse_args(["evals", "longmemeval", "--smoke"])
    assert ns_default.answer_max_tokens == 2048

    ns_explicit = parser.parse_args(
        ["evals", "longmemeval", "--smoke", "--answer-max-tokens", "1024"]
    )
    assert ns_explicit.answer_max_tokens == 1024
