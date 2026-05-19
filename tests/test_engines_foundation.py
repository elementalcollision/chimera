"""Tests for the engines foundation — ChronicleManager + EngineScheduler."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from chimera.engines import ChronicleManager, EngineScheduler


# ── ChronicleManager ────────────────────────────────────────


def test_chronicle_creates_header_when_missing(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    cm.upsert_section(section_name="Morning Discovery", body="first content", day="2026-05-19")
    text = (tmp_path / "CHRONICLE.md").read_text()
    assert text.startswith("# Chimera — Chronicle")
    assert "## 2026-05-19" in text
    assert "### Morning Discovery" in text
    assert "first content" in text


def test_chronicle_upsert_replaces_existing_section(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    cm.upsert_section(
        section_name="Morning Discovery", body="ORIGINAL_BODY_xyz", day="2026-05-19"
    )
    cm.upsert_section(
        section_name="Morning Discovery", body="REPLACEMENT_BODY_xyz", day="2026-05-19"
    )
    text = (tmp_path / "CHRONICLE.md").read_text()
    assert "ORIGINAL_BODY_xyz" not in text
    assert "REPLACEMENT_BODY_xyz" in text
    # Still only one Morning Discovery heading.
    assert text.count("### Morning Discovery") == 1


def test_chronicle_appends_new_sections_within_day(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    cm.upsert_section(section_name="Morning Discovery", body="m", day="2026-05-19")
    cm.upsert_section(section_name="Midday Curiosity", body="c", day="2026-05-19")
    cm.upsert_section(section_name="Evening Reflection", body="r", day="2026-05-19")
    text = (tmp_path / "CHRONICLE.md").read_text()
    for s in ("### Morning Discovery", "### Midday Curiosity", "### Evening Reflection"):
        assert s in text


def test_chronicle_inserts_new_day_at_top(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    cm.upsert_section(section_name="Morning Discovery", body="older", day="2026-05-18")
    cm.upsert_section(section_name="Morning Discovery", body="newer", day="2026-05-19")
    text = (tmp_path / "CHRONICLE.md").read_text()
    # Newer day appears before the older day.
    assert text.index("## 2026-05-19") < text.index("## 2026-05-18")


def test_chronicle_day_section_returns_content(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    cm.upsert_section(section_name="Morning Discovery", body="hello", day="2026-05-19")
    content = cm.day_section(day="2026-05-19")
    assert "### Morning Discovery" in content
    assert "hello" in content


def test_chronicle_day_section_returns_empty_when_missing(tmp_path: Path):
    cm = ChronicleManager(tmp_path / "CHRONICLE.md")
    assert cm.day_section(day="1999-01-01") == ""


# ── EngineScheduler ─────────────────────────────────────────


def _at(hour: int) -> dt.datetime:
    return dt.datetime(2026, 5, 19, hour, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def scheduler_path(tmp_path: Path) -> Path:
    return tmp_path / "engines" / "last_runs.json"


def test_scheduler_picks_discovery_in_morning_window(scheduler_path):
    s = EngineScheduler(scheduler_path)
    assert s.pick_due(now=_at(8)) == "discovery"
    assert s.pick_due(now=_at(13)) == "discovery"


def test_scheduler_picks_curiosity_in_afternoon_window(scheduler_path):
    s = EngineScheduler(scheduler_path)
    assert s.pick_due(now=_at(14)) == "curiosity"
    assert s.pick_due(now=_at(21)) == "curiosity"


def test_scheduler_picks_reflection_late_or_early_morning(scheduler_path):
    s = EngineScheduler(scheduler_path)
    assert s.pick_due(now=_at(22)) == "reflection"
    assert s.pick_due(now=_at(3)) == "reflection"


def test_scheduler_per_day_gate_blocks_second_run(scheduler_path):
    s = EngineScheduler(scheduler_path)
    assert s.pick_due(now=_at(8)) == "discovery"
    s.mark_ran("discovery", now=_at(8))
    assert s.pick_due(now=_at(9)) is None


def test_scheduler_force_bypasses_gates(scheduler_path):
    s = EngineScheduler(scheduler_path)
    s.mark_ran("discovery", now=_at(8))
    # Mid-morning, discovery already ran; force still works.
    assert s.pick_due(now=_at(9), force="discovery") == "discovery"


def test_scheduler_per_day_state_persists_across_instances(scheduler_path):
    s1 = EngineScheduler(scheduler_path)
    s1.mark_ran("discovery", now=_at(8))
    s2 = EngineScheduler(scheduler_path)
    assert s2.snapshot() == {"discovery": "2026-05-19"}
    assert s2.pick_due(now=_at(9)) is None


def test_scheduler_env_overrides(monkeypatch, scheduler_path):
    monkeypatch.setenv("CHIMERA_DISCOVERY_HOUR", "5")
    monkeypatch.setenv("CHIMERA_CURIOSITY_HOUR", "10")
    monkeypatch.setenv("CHIMERA_REFLECTION_HOUR", "18")
    s = EngineScheduler(scheduler_path)
    assert s.pick_due(now=_at(5)) == "discovery"
    assert s.pick_due(now=_at(10)) == "curiosity"
    assert s.pick_due(now=_at(18)) == "reflection"
