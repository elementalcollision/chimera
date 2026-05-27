"""Tests for the LoCoMo adapter (ADR 0144).

Scope: corpus loading, item expansion, category-int → label mapping,
ingest/answer cycle, sample-ingest cache, batch-runner filters
(subset / sample-id / per-cat / limit), grader prompt-template
dispatch, CLI flag wiring. Empirical sweep results live in the
baseline note + ADR, not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.evals.locomo import (
    CATEGORY_INT_TO_LABEL,
    LoCoMoAdapter,
    LoCoMoItem,
    canonical_category,
    items_from_sample,
    load_items,
    run_batch,
    summarize_results,
    write_results,
)


# ── Category taxonomy ────────────────────────────────────────────


def test_canonical_category_int_to_label():
    assert canonical_category(1) == "single-hop"
    assert canonical_category(2) == "multi-hop"
    assert canonical_category(3) == "temporal-reasoning"
    assert canonical_category(4) == "open-domain"
    assert canonical_category(5) == "adversarial"


def test_canonical_category_string_passthrough_and_fallback():
    assert canonical_category("single-hop") == "single-hop"
    assert canonical_category("not-a-real-cat") == "(uncategorised)"
    assert canonical_category(None) == "(uncategorised)"  # type: ignore[arg-type]
    assert canonical_category(99) == "(uncategorised)"
    # Numeric strings flow through the int path.
    assert canonical_category("3") == "temporal-reasoning"


# ── items_from_sample / load_items ───────────────────────────────


@pytest.fixture
def sample_dict() -> dict:
    return {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1_date_time": "1 Jan 2026",
            "session_1": [
                {"speaker": "Alice", "dia_id": "D1:1", "text": "I got a cat."},
                {"speaker": "Bob", "dia_id": "D1:2", "text": "Name?"},
                {"speaker": "Alice", "dia_id": "D1:3", "text": "Pixel."},
            ],
            "session_2_date_time": "8 Jan 2026",
            "session_2": [
                {"speaker": "Alice", "dia_id": "D2:1", "text": "Pixel's settled in."},
            ],
        },
        "qa": [
            {"question": "Pet name?", "answer": "Pixel",
             "evidence": ["D1:3"], "category": 1},
            {"question": "When did Alice talk about Pixel settling in?",
             "answer": "8 Jan 2026", "evidence": ["D2:1"], "category": 3},
            {"question": "What's Bob's favorite color?",
             "answer": "unanswerable", "evidence": [], "category": 5},
        ],
    }


def test_items_from_sample_expands_qa(sample_dict):
    items = items_from_sample(sample_dict)
    assert len(items) == 3
    assert {i.item_id for i in items} == {
        "conv-test::qa0", "conv-test::qa1", "conv-test::qa2",
    }
    assert items[0].category == "single-hop"
    assert items[1].category == "temporal-reasoning"
    assert items[2].category == "adversarial"
    # All share sessions + speakers.
    for it in items:
        assert it.sample_id == "conv-test"
        assert it.speaker_a == "Alice" and it.speaker_b == "Bob"
        assert len(it.sessions) == 2
        assert it.session_dates == ["1 Jan 2026", "8 Jan 2026"]


def test_items_from_sample_role_mapping(sample_dict):
    items = items_from_sample(sample_dict)
    sess0 = items[0].sessions[0]
    # speaker_a (Alice) → user, speaker_b (Bob) → assistant.
    roles = [t["role"] for t in sess0]
    assert roles == ["user", "assistant", "user"]
    # Real speaker name is preserved.
    assert sess0[0]["speaker"] == "Alice"
    assert sess0[1]["speaker"] == "Bob"


def test_items_from_sample_question_date_is_latest_session(sample_dict):
    items = items_from_sample(sample_dict)
    # "Today" anchor = latest session_dates entry (post-T1.5 grounding).
    assert items[0].question_date == "8 Jan 2026"


def test_load_items_round_trip(tmp_path, sample_dict):
    p = tmp_path / "locomo10.json"
    p.write_text(json.dumps([sample_dict]))
    items = load_items(p)
    assert len(items) == 3
    assert all(i.sample_id == "conv-test" for i in items)


def test_load_items_empty_when_missing(tmp_path):
    assert load_items(tmp_path / "no-such-file.json") == []


# ── Adapter ──────────────────────────────────────────────────────


@pytest.fixture
def adapter(tmp_path: Path) -> LoCoMoAdapter:
    return LoCoMoAdapter(mind_dir=tmp_path / "mind")


def test_ingest_writes_self_card_with_speakers_and_today(adapter, tmp_path, sample_dict):
    items = items_from_sample(sample_dict)
    written = adapter.ingest_history(items[0])
    assert written == 2  # one file per session
    self_card = (tmp_path / "mind" / "peers" / "self.md").read_text()
    # Real speaker names appear in the card.
    assert "Alice" in self_card
    assert "Bob" in self_card
    # "Today" anchor from the latest session.
    assert "**Today's date:** 8 Jan 2026" in self_card
    assert self_card.index("Today's date:") < self_card.index("## History")
    # Per-session scratch files written.
    scratch = tmp_path / "mind" / "wiki" / "locomo"
    assert len(list(scratch.glob("*.md"))) == 2


def test_ingest_cache_skips_sibling_qas(adapter, sample_dict):
    """All three QAs share the same conversation. After the first
    ingest, sibling items should be no-ops (return 0)."""
    items = items_from_sample(sample_dict)
    assert adapter.ingest_history(items[0]) == 2
    assert adapter.ingest_history(items[1]) == 0
    assert adapter.ingest_history(items[2]) == 0


def test_ingest_cache_invalidates_on_new_sample(adapter, sample_dict):
    items = items_from_sample(sample_dict)
    adapter.ingest_history(items[0])
    # Construct a synthetic second sample sharing the adapter.
    other_sample = dict(sample_dict, sample_id="conv-other")
    other_items = items_from_sample(other_sample)
    # Different sample_id → ingest runs again (returns >0).
    assert adapter.ingest_history(other_items[0]) == 2


def test_reset_force_clears_scratch_and_cache(adapter, tmp_path, sample_dict):
    items = items_from_sample(sample_dict)
    adapter.ingest_history(items[0])
    scratch = tmp_path / "mind" / "wiki" / "locomo"
    assert len(list(scratch.glob("*.md"))) == 2
    adapter.reset(force=True)
    assert list(scratch.glob("*.md")) == []
    # Cache cleared — next ingest runs.
    assert adapter.ingest_history(items[0]) == 2


def test_cleanup_race_file_vanishes_between_iterdir_and_unlink(
    adapter, tmp_path, sample_dict, monkeypatch,
):
    """Regression for the F2 conv-41-s029.md crash.

    iterdir() yields a path, then the file disappears (concurrent
    cleanup, filesystem quirk, etc.) before unlink() reaches it. The
    adapter must not crash with FileNotFoundError — `missing_ok=True`
    on the unlink is the contract.
    """
    items = items_from_sample(sample_dict)
    adapter.ingest_history(items[0])
    scratch = tmp_path / "mind" / "wiki" / "locomo"
    assert len(list(scratch.glob("*.md"))) == 2

    # Simulate: iterdir → is_file is True → file vanishes → unlink races.
    # Achieved by intercepting unlink so the first call vaporises the file
    # and the second call (the one inside the cleanup loop, since we
    # double up to model the race) hits FileNotFoundError unless
    # missing_ok=True is honoured.
    import os

    real_unlink = Path.unlink

    def racy_unlink(self, *, missing_ok=False):
        # Remove the underlying file out-of-band, then call the real
        # unlink — emulates a concurrent removal between is_file() and
        # unlink(). Without missing_ok=True this raises FileNotFoundError.
        try:
            os.unlink(self)
        except FileNotFoundError:
            pass
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", racy_unlink)

    # Force a fresh ingest path (new sample_id → cleanup runs).
    other_items = items_from_sample(dict(sample_dict, sample_id="conv-next"))
    # Pre-fix this raised FileNotFoundError; post-fix it returns cleanly.
    assert adapter.ingest_history(other_items[0]) == 2


def test_answer_returns_grounded_prompt(adapter, sample_dict):
    items = items_from_sample(sample_dict)
    adapter.ingest_history(items[0])
    res = adapter.answer(items[0])
    # Without an answer_fn, `answer` field carries the assembled prompt.
    assert items[0].question in res.answer
    assert res.hypothesis is None
    assert res.expected_answer == "Pixel"
    assert res.sample_id == "conv-test"
    assert res.category == "single-hop"


def test_answer_swallows_adapter_failure(adapter, sample_dict, monkeypatch):
    """A bad dialectic call must not kill the sweep — error → AnswerResult.error."""
    items = items_from_sample(sample_dict)
    adapter.ingest_history(items[0])

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("chimera.a2a.dialectic.gather_dialectic_context", boom)
    res = adapter.answer(items[0])
    assert res.error == "synthetic failure"
    assert res.answer == ""


# ── Batch runner ─────────────────────────────────────────────────


def test_run_batch_per_category_limit(adapter, sample_dict):
    items = items_from_sample(sample_dict)
    # With cap=1/cat, expect at most one per (single-hop, temporal-reasoning,
    # adversarial) = 3 distinct cats present in sample.
    results = run_batch(adapter, items, per_category_limit=1)
    cats = [r.category for r in results]
    assert len(cats) == 3
    assert set(cats) == {"single-hop", "temporal-reasoning", "adversarial"}


def test_run_batch_filters_by_subset_and_sample_id(adapter, sample_dict):
    items = items_from_sample(sample_dict)
    only_temporal = run_batch(adapter, items, subset="temporal")
    assert [r.category for r in only_temporal] == ["temporal-reasoning"]
    # Negative sample_id filter returns nothing.
    none = run_batch(adapter, items, sample_id="no-such-conv")
    assert none == []
    # Positive substring matches the sample.
    matched = run_batch(adapter, items, sample_id="conv-test")
    assert len(matched) == 3


# ── JSONL write / summarize ──────────────────────────────────────


def test_write_and_summarize_round_trip(tmp_path):
    rows = [
        {"item_id": "x::qa0", "category": "single-hop", "is_correct": True},
        {"item_id": "x::qa1", "category": "single-hop", "is_correct": False},
        {"item_id": "x::qa2", "category": "adversarial", "is_correct": True},
    ]
    p = tmp_path / "graded.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summary = summarize_results(p)
    assert summary["single-hop"] == {"total": 2, "correct": 1, "accuracy": 0.5}
    assert summary["adversarial"] == {"total": 1, "correct": 1, "accuracy": 1.0}
    assert summary["_overall"]["accuracy"] == pytest.approx(2 / 3, rel=1e-4)


# ── Grader prompt-template dispatch ──────────────────────────────


def test_grader_prompt_dispatch_by_category():
    """grade_locomo.get_anscheck_prompt routes by canonical category."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "grade_locomo",
        Path(__file__).resolve().parents[1] / "scripts" / "grade_locomo.py",
    )
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Adversarial routes to the unanswerable-detection template.
    p_adv = mod.get_anscheck_prompt("adversarial", "Q?", "EXPL", "RESP")
    assert "unanswerable" in p_adv.lower()

    # Temporal-reasoning includes off-by-one tolerance language.
    p_tr = mod.get_anscheck_prompt("temporal-reasoning", "Q?", "A", "R")
    assert "off-by-one" in p_tr.lower()

    # Single-hop / multi-hop / open-domain all share the same template,
    # which does NOT have off-by-one language.
    p_sh = mod.get_anscheck_prompt("single-hop", "Q?", "A", "R")
    assert "off-by-one" not in p_sh.lower()
    assert "unanswerable" not in p_sh.lower()


def test_grader_blocklist_includes_reasoning_judges():
    """ADR 0143 footgun guard must survive the copy-from-LongMemEval."""
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "grade_locomo",
        Path(__file__).resolve().parents[1] / "scripts" / "grade_locomo.py",
    )
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert "openai/o4-mini" in mod._REASONING_JUDGE_BLOCKLIST
    assert mod.DEFAULT_JUDGE == "openai/gpt-4o-mini"


# ── CLI flag wiring (regression guard for argparse drift) ────────


def test_cli_evals_locomo_help_lists_all_flags():
    """Smoke check the CLI parser actually exposes the chip's flags."""
    from chimera.cli import _build_parser
    parser = _build_parser()
    # argparse doesn't expose subparsers by attribute; we parse a known
    # invocation that should succeed at the parse step.
    args = parser.parse_args([
        "evals", "locomo",
        "--smoke",
        "--n-per-category", "2",
        "--hybrid-retrieval",
        "--retrieval-top-k", "4",
        "--sample-id", "conv-test",
        "--answer-temperature", "0",
        "--answer-max-tokens", "1024",
    ])
    assert args.command == "evals"
    assert args.evals_command == "locomo"
    assert args.smoke is True
    assert args.n_per_category == 2
    assert args.hybrid_retrieval is True
    assert args.retrieval_top_k == 4
    assert args.sample_id == "conv-test"
    assert args.answer_temperature == 0.0
    assert args.answer_max_tokens == 1024
