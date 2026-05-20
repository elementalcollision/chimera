"""Tests for v4.5 adaptive budgets + fragmentation auto-mutation (L-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.adaptation import (
    count_similar,
    list_fragmentation,
    maybe_propose_synthesis_skill,
    record_fragmentation,
    signature,
)
from chimera.core.budget import dynamic_max_rounds
from chimera.memory import list_mutations, open_and_init


# ── budget ──────────────────────────────────────────────────


def test_dynamic_max_rounds_matches_base_for_trivial_task():
    assert dynamic_max_rounds("Just say hello.", base=12) == 12


def test_dynamic_max_rounds_grows_with_declared_artifacts():
    # Two artifacts × per_artifact=4 → +8 above base.
    text = "Write to `state/a.log` and to `mind/b.md`."
    assert dynamic_max_rounds(text, base=12, per_artifact=4, per_tool=0) == 20


def test_dynamic_max_rounds_grows_with_tool_keywords():
    # web_search + code_exec → +4 above base (per_tool=2).
    text = "Use web_search to find sources, then code_exec to count words."
    assert dynamic_max_rounds(text, base=12, per_artifact=0, per_tool=2) == 16


def test_dynamic_max_rounds_caps_at_ceiling():
    text = (
        "Use web_search + http_fetch + code_exec + shell + spawn_sub_agent to "
        "produce `state/a.log`, `state/b.log`, `state/c.log`, `state/d.log`."
    )
    assert dynamic_max_rounds(text, base=12, cap=32) == 32


# ── v4.47: tier multiplier ──────────────────────────────────


def test_dynamic_max_rounds_haiku_is_baseline():
    text = "Quick triage of mind/notes.md"
    assert dynamic_max_rounds(text, base=12, tier="haiku") == 12


def test_dynamic_max_rounds_sonnet_promotes_budget():
    text = "Quick triage of mind/notes.md"
    # base=12 × 1.5 = 18.
    assert dynamic_max_rounds(text, base=12, tier="sonnet") == 18


def test_dynamic_max_rounds_opus_doubles_budget():
    text = "Quick triage of mind/notes.md"
    # base=12 × 2.0 = 24.
    assert dynamic_max_rounds(text, base=12, tier="opus") == 24


def test_dynamic_max_rounds_opus_scales_the_cap_too():
    # Compound task that pegs haiku at cap=32 should not be truncated
    # to 32 when promoted — the cap scales with tier so opus sees ~64.
    text = (
        "Use web_search + http_fetch + code_exec + shell + spawn_sub_agent to "
        "produce `state/a.log`, `state/b.log`, `state/c.log`, `state/d.log`."
    )
    haiku = dynamic_max_rounds(text, base=12, cap=32, tier="haiku")
    opus = dynamic_max_rounds(text, base=12, cap=32, tier="opus")
    assert haiku == 32
    assert opus == 64  # cap × 2.0


def test_dynamic_max_rounds_unknown_tier_defaults_to_haiku_multiplier():
    text = "Quick triage of mind/notes.md"
    # Unknown tier name → multiplier 1.0 (no promotion).
    assert dynamic_max_rounds(text, base=12, tier="weird") == 12


# ── signature + log ─────────────────────────────────────────


def test_signature_drops_stopwords_and_lowercases():
    sig = signature("Combine the summary AND the critique into one document.")
    assert "combine" in sig
    assert "summary" in sig
    assert "critique" in sig
    assert "document" in sig
    # short words are filtered out
    assert "and" not in sig and "the" not in sig


def test_record_and_list_round_trip(tmp_path: Path):
    log = tmp_path / "frag.jsonl"
    rec = record_fragmentation(
        cycle=1,
        task_text="Combine summary and critique into `mind/final.md`.",
        rounds_used=12,
        tool_call_count=21,
        missing_artifacts=["mind/final.md"],
        path=log,
    )
    rows = list_fragmentation(path=log)
    assert len(rows) == 1
    assert rows[0].cycle == rec.cycle
    assert rows[0].missing_artifacts == ("mind/final.md",)


def test_count_similar_jaccard_overlap(tmp_path: Path):
    log = tmp_path / "frag.jsonl"
    record_fragmentation(
        cycle=1,
        task_text="Combine the summary with the critique into one final document.",
        rounds_used=12,
        tool_call_count=21,
        missing_artifacts=["mind/final.md"],
        path=log,
    )
    record_fragmentation(
        cycle=2,
        task_text="Merge the summary plus critique into a single conclusion document.",
        rounds_used=12,
        tool_call_count=24,
        missing_artifacts=["mind/conclusion.md"],
        path=log,
    )
    # Same conceptual task → both should match each other.
    similar = count_similar(
        "Combine summary and critique into one conclusion document.", path=log
    )
    assert similar >= 1
    # Wildly different task should not match.
    assert count_similar("Compute the SHA-256 of bytes b'hi'.", path=log) == 0


# ── auto-mutation proposal ──────────────────────────────────


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_maybe_propose_emits_mutation_when_threshold_met(
    tmp_path: Path, db
):
    log = tmp_path / "frag.jsonl"
    # Two similar prior records.
    for cycle in (1, 2):
        record_fragmentation(
            cycle=cycle,
            task_text="Combine the summary with the critique into one final document.",
            rounds_used=12,
            tool_call_count=21,
            missing_artifacts=["mind/final.md"],
            path=log,
        )
    mid = maybe_propose_synthesis_skill(
        db,
        cycle=3,
        task_text="Combine summary and critique into one conclusion document.",
        missing_artifacts=["mind/conclusion.md"],
        path=log,
    )
    assert mid is not None
    rows = list_mutations(db, type="skill_proposal")
    assert len(rows) == 1
    assert rows[0].payload["name"] == "synthesize_to_file"
    assert rows[0].payload["similar_count"] >= 2


def test_maybe_propose_silent_when_no_prior_history(tmp_path: Path, db):
    log = tmp_path / "frag.jsonl"
    mid = maybe_propose_synthesis_skill(
        db,
        cycle=1,
        task_text="One-off task with no prior failure history.",
        missing_artifacts=["mind/x.md"],
        path=log,
    )
    assert mid is None
    assert list_mutations(db, type="skill_proposal") == []


def test_maybe_propose_does_not_duplicate(tmp_path: Path, db):
    log = tmp_path / "frag.jsonl"
    for cycle in (1, 2):
        record_fragmentation(
            cycle=cycle,
            task_text="Combine summary and critique into one final document.",
            rounds_used=12, tool_call_count=21,
            missing_artifacts=["mind/final.md"],
            path=log,
        )
    first = maybe_propose_synthesis_skill(
        db,
        cycle=3,
        task_text="Combine summary and critique into one final document.",
        missing_artifacts=["mind/final.md"],
        path=log,
    )
    second = maybe_propose_synthesis_skill(
        db,
        cycle=4,
        task_text="Combine summary and critique into one final document.",
        missing_artifacts=["mind/final.md"],
        path=log,
    )
    assert first is not None
    # v4.19: duplicate signature returns the existing id (so the caller
    # can see something happened) and bumps recurrence_count in-place
    # instead of enqueueing a new row.
    assert second == first
    from chimera.memory import get_mutation
    m = get_mutation(db, first)
    assert m is not None and m.recurrence_count == 1
    assert len(list_mutations(db, type="skill_proposal")) == 1
