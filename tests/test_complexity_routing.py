"""Tests for the lexical task-complexity model selection (ADR 0166)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import (
    complexity_floor_tier,
    complexity_routing_enabled,
    recommended_tier,
)
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── classifier: complexity_floor_tier ──────────────────────────────


def test_simple_lookup_has_no_floor():
    assert complexity_floor_tier("what is the capital of France") is None
    assert complexity_floor_tier("summarise mind/INBOX.md") is None
    assert complexity_floor_tier("") is None


def test_single_reasoning_verb_floors_sonnet():
    assert complexity_floor_tier("refactor the parser module") == "sonnet"
    assert complexity_floor_tier("diagnose the failing import") == "sonnet"


def test_breadth_two_floors_sonnet():
    # web_search + write-to → breadth 2, no reasoning verb.
    got = complexity_floor_tier(
        "search the web for the latest figures and save to mind/out.md"
    )
    assert got == "sonnet"


def test_multistep_phrasing_floors_sonnet():
    got = complexity_floor_tier(
        "read the config and then update the dashboard label"
    )
    assert got == "sonnet"


def test_numbered_list_is_multistep():
    task = "Do the work:\n1. read the file\n2. update it\n3. verify"
    assert complexity_floor_tier(task) == "sonnet"


def test_high_bar_floors_opus():
    # reasoning verb + multi-step + breadth >= 2.
    task = (
        "Refactor chimera/core/act.py, then run the python test suite and "
        "save to mind/report.md"
    )
    assert complexity_floor_tier(task) == "opus"


def test_three_reasoning_verbs_floors_opus():
    assert (
        complexity_floor_tier("design, implement, and benchmark the cache")
        == "opus"
    )


def test_reasoning_verbs_matched_whole_word():
    # "implementation" contains "implement" as a substring but the verb
    # match is whole-word, so a noun mention alone does not over-trigger.
    assert complexity_floor_tier("describe the implementation details") is None


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nope", False),
])
def test_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", val)
    assert complexity_routing_enabled() is expected


def test_flag_on_by_default(monkeypatch):
    # ADR 0185 graduation (2026-06-20): unset → ON (registry default "1").
    monkeypatch.delenv("CHIMERA_COMPLEXITY_ROUTING", raising=False)
    assert complexity_routing_enabled()


# ── integration: recommended_tier ──────────────────────────────────


def test_flag_explicit_disable_keeps_default_tier(monkeypatch, db):
    # ADR 0185: default-ON now, so the no-lift (v4.119) behaviour requires an
    # EXPLICIT opt-out (CHIMERA_COMPLEXITY_ROUTING=0). A clearly-complex task with
    # no escalation history then stays at the default haiku tier.
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "0")
    task = "Refactor chimera/core/act.py and then run python tests"
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "haiku"


def test_flag_on_lifts_to_sonnet(monkeypatch, db):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "1")
    assert (
        recommended_tier(db, task_text="refactor the parser", default_tier="haiku")
        == "sonnet"
    )


def test_flag_on_lifts_to_opus(monkeypatch, db):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "1")
    task = (
        "Refactor chimera/core/act.py, then run the python suite and save "
        "to mind/report.md"
    )
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "opus"


def test_flag_on_never_demotes_below_default(monkeypatch, db):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "1")
    # A simple task with default sonnet must not be pulled down to haiku.
    assert (
        recommended_tier(db, task_text="say hello", default_tier="sonnet")
        == "sonnet"
    )


def test_flag_on_simple_task_stays_default(monkeypatch, db):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", "1")
    assert (
        recommended_tier(db, task_text="what is 2 plus 2", default_tier="haiku")
        == "haiku"
    )
