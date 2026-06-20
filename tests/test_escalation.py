"""Direct unit tests for ``chimera/core/escalation.py``.

Complements the indirect coverage in test_task_escalation.py (happy-path
record/promote + ACT integration), test_guards.py (PR #58 plan basics),
test_hot_signatures*.py, test_research_tier_floor.py and
test_complexity_routing.py. This module targets the gaps: signature
normalisation edge cases, malformed / pre-migration DB states, Jaccard
threshold boundaries, tier clamping and demotion guards, reader limits,
and the complexity-signal regex branches.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from chimera.core.escalation import (
    ESCALATING_FINISH_REASONS,
    _complexity_signals,
    _signature,
    build_correction_prompt,
    build_escalation_plan,
    clear_escalations,
    complexity_floor_tier,
    complexity_routing_enabled,
    escalation_summary,
    hot_signatures,
    list_escalations,
    record_failure,
    recommended_tier,
)
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.fixture
def bare_db():
    """A connection with NO chimera schema — the pre-migration state."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _record(conn, task, *, tier="haiku", reason="max_rounds", rounds=12, cycle=1):
    return record_failure(
        conn, task_text=task, tier=tier, finish_reason=reason,
        rounds_used=rounds, cycle=cycle,
    )


# ── _signature normalisation ─────────────────────────────────


def test_signature_token_length_boundary():
    # 3-char tokens dropped, 4-char tokens kept.
    assert _signature("abc abcd") == "abcd"
    assert _signature("the and for") == ""


def test_signature_handles_none_and_numeric_tokens():
    assert _signature(None) == ""
    # Numeric runs >= 4 chars are real tokens (years, versions).
    assert _signature("send 2026 report") == "2026,report,send"


def test_signature_non_ascii_splits_to_empty():
    # The token regex is ASCII-only: accented words fragment below the
    # 4-char floor, so the signature is empty and nothing is recorded.
    assert _signature("naïve café déjà") == ""


def test_signature_dedupes_repeated_tokens():
    assert _signature("alpha alpha ALPHA beta") == "alpha,beta"


# ── record_failure ───────────────────────────────────────────


@pytest.mark.parametrize("reason", sorted(ESCALATING_FINISH_REASONS))
def test_record_failure_accepts_every_escalating_reason(db, reason):
    rid = _record(db, "build the synthesis report artifact", reason=reason)
    assert rid is not None and rid > 0


def test_record_failure_missing_table_is_graceful(bare_db):
    # Pre-migration DB: no task_escalations table → None, not a raise.
    assert _record(bare_db, "build the synthesis report artifact") is None


def test_record_failure_created_at_is_utc_iso(db):
    before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
    _record(db, "build the synthesis report artifact")
    raw = db.execute("SELECT created_at FROM task_escalations").fetchone()[0]
    stamp = dt.datetime.fromisoformat(raw)
    assert stamp.utcoffset() == dt.timedelta(0)
    assert stamp >= before


# ── recommended_tier: malformed / boundary states ────────────


def test_recommended_tier_missing_table_returns_default(bare_db):
    got = recommended_tier(
        bare_db, task_text="build the synthesis report artifact",
        default_tier="haiku",
    )
    assert got == "haiku"


def test_recommended_tier_empty_task_ignores_history(db):
    _record(db, "build the synthesis report artifact")
    assert recommended_tier(db, task_text="", default_tier="haiku") == "haiku"
    assert recommended_tier(db, task_text="ab cd", default_tier="haiku") == "haiku"


def test_recommended_tier_skips_empty_signature_rows(db):
    task = "build the synthesis report artifact"
    # A malformed row (empty signature) must not crash or match.
    # (NULL is rejected by the schema's NOT NULL constraint; the
    # ``r["signature"] or ""`` guard covers legacy DBs without it.)
    db.execute(
        "INSERT INTO task_escalations "
        "(signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
        "VALUES ('', '', 'haiku', 'max_rounds', 1, 1, '2026-01-01T00:00:00+00:00')",
    )
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "haiku"
    # A valid matching row alongside the NULL row still promotes.
    _record(db, task)
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "sonnet"


def test_recommended_tier_unknown_historic_tier_no_promotion(db):
    task = "build the synthesis report artifact"
    db.execute(
        "INSERT INTO task_escalations "
        "(signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
        "VALUES (?, ?, 'turbo', 'max_rounds', 1, 1, '2026-01-01T00:00:00+00:00')",
        (_signature(task), task),
    )
    # Unknown tier ranks below the ladder → defensive default, no promote.
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "haiku"


def test_recommended_tier_jaccard_threshold_is_inclusive(db):
    # incoming {alpha,bravo} vs recorded {alpha,bravo,carol,delta}
    # → overlap 2/4 == 0.5, exactly at the default threshold → match.
    _record(db, "alpha bravo carol delta")
    assert recommended_tier(db, task_text="alpha bravo", default_tier="haiku") == "sonnet"


def test_recommended_tier_below_threshold_and_custom_threshold(db):
    # incoming {alpha,bravo} vs recorded 5-token set → 2/5 = 0.4 < 0.5.
    _record(db, "alpha bravo carol delta echos")
    assert recommended_tier(db, task_text="alpha bravo", default_tier="haiku") == "haiku"
    # Loosening the threshold flips the same history into a match.
    got = recommended_tier(
        db, task_text="alpha bravo", default_tier="haiku", overlap_threshold=0.4,
    )
    assert got == "sonnet"


def test_recommended_tier_never_demotes_below_default(db):
    task = "build the synthesis report artifact"
    _record(db, task, tier="haiku")
    # Promotion lands at sonnet, but the caller default is opus → opus.
    assert recommended_tier(db, task_text=task, default_tier="opus") == "opus"


def test_recommended_tier_paraphrase_promotes(db):
    # Same token bag, different order / case / punctuation → same
    # signature → full-overlap match against the recorded failure.
    _record(db, "build agonistic futures world model")
    got = recommended_tier(
        db,
        task_text="MODEL!! world... agonistic; futures (build)",
        default_tier="haiku",
    )
    assert got == "sonnet"


# ── operator readers: limits + degenerate states ─────────────


def test_list_escalations_limit_caps_results(db):
    for i in range(5):
        _record(db, f"task number {i} alpha beta gamma", cycle=i)
    rows = list_escalations(db, limit=2)
    assert len(rows) == 2
    assert [r.cycle for r in rows] == [4, 3]  # most recent first


def test_list_escalations_row_roundtrip(db):
    task = "deliver quarterly metrics artifact"
    _record(db, task, tier="sonnet", reason="artifact_missing", rounds=7, cycle=42)
    (row,) = list_escalations(db)
    assert row.task_text == task
    assert row.signature == _signature(task)
    assert row.tier == "sonnet"
    assert row.finish_reason == "artifact_missing"
    assert row.rounds_used == 7
    assert row.cycle == 42
    assert row.id > 0 and row.created_at


def test_readers_missing_table_return_empty(bare_db):
    assert list_escalations(bare_db) == []
    assert escalation_summary(bare_db) == {}
    assert hot_signatures(bare_db) == []
    assert clear_escalations(bare_db) == 0


def test_escalation_summary_distinct_signatures(db):
    _record(db, "build agonistic futures world model")
    _record(db, "compute fibonacci sequence quickly", cycle=2)
    summary = escalation_summary(db)
    assert len(summary) == 2
    assert all(counts == {"haiku": 1} for counts in summary.values())


def test_clear_escalations_no_match_returns_zero(db):
    _record(db, "build agonistic futures world model")
    assert clear_escalations(db, signature_substring="zzznotthere") == 0
    assert len(list_escalations(db)) == 1


def test_hot_signatures_tiers_deduped_sorted_and_cycles(db):
    task = "build agonistic futures world model"
    _record(db, task, tier="sonnet", cycle=3)
    _record(db, task, tier="haiku", cycle=5)
    _record(db, task, tier="sonnet", cycle=9)
    (hot,) = hot_signatures(db)
    assert hot.tiers == ["haiku", "sonnet"]
    assert hot.total_failures == 3
    assert hot.first_seen_cycle == 3
    assert hot.last_seen_cycle == 9


# ── PR #58 plan helpers: clamping + degenerate inputs ────────


def test_correction_prompt_placeholders_and_sorted_writes():
    prompt = build_correction_prompt("do the thing", [], ["b.md", "a.md"])
    assert "(none extracted)" in prompt
    assert "a.md, b.md" in prompt


def test_escalation_plan_opus_first_miss_clamps_at_top():
    plan = build_escalation_plan(
        task_text="write the file",
        expected_paths=["out.md"],
        actual_writes=[],
        current_tier="opus",
        retries_used=0,
    )
    assert plan.retry is True
    assert plan.next_tier == "opus"  # top of ladder, no overshoot


def test_escalation_plan_zero_max_retries_never_retries():
    plan = build_escalation_plan(
        task_text="write the file",
        expected_paths=["out.md"],
        actual_writes=[],
        current_tier="haiku",
        retries_used=0,
        max_retries=0,
    )
    assert plan.retry is False
    assert plan.next_tier == "haiku"  # stays put on terminal failure
    assert "out.md" in plan.correction_prompt


# ── complexity signals: regex branches ───────────────────────


def test_complexity_signals_empty_inputs():
    assert _complexity_signals("") == (0, 0, False)
    assert _complexity_signals(None) == (0, 0, False)


def test_complexity_two_distinct_path_deliverables_is_multistep():
    # No reasoning verb, no breadth, no multistep phrase — only the
    # two-distinct-paths regex fires → sonnet floor.
    task = "update docs/alpha.md and docs/bravo.md"
    assert _complexity_signals(task) == (0, 0, True)
    assert complexity_floor_tier(task) == "sonnet"


def test_complexity_duplicate_path_and_single_numbered_item_no_floor():
    # The same path twice is ONE deliverable (set semantics) → no floor.
    assert complexity_floor_tier("update docs/alpha.md and docs/alpha.md again") is None
    # A single numbered item is not a multi-step list (needs >= 2).
    assert complexity_floor_tier("1. update the dashboard") is None


def test_complexity_flag_strips_whitespace_and_casefolds(monkeypatch):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "  TRUE  ")
    assert complexity_routing_enabled() is True
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "ON")
    assert complexity_routing_enabled() is True
    # ADR 0185: default-ON now, so test the parser's falsey path with an explicit
    # whitespace-wrapped opt-out (not the unset default, which is now ON).
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "  off  ")
    assert complexity_routing_enabled() is False
