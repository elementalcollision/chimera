"""Tests for the 8-phase Chimera loop (ACT stubbed)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_live_providers(monkeypatch):
    """Tests here don't want ACT to actually call providers."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

from chimera.core import (
    ChimeraLoop,
    LoopConfig,
    load_heartbeat,
    mark_inbox_tasks_done,
    parse_inbox,
    save_heartbeat,
)
from chimera.core.mind import HeartbeatState


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mind_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mind"
    d.mkdir()
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def config(mind_dir: Path, state_dir: Path) -> LoopConfig:
    return LoopConfig(mind_dir=mind_dir, state_dir=state_dir)


# ── mind.py: frontmatter + INBOX ────────────────────────────


def test_load_heartbeat_missing_file_returns_defaults(mind_dir: Path):
    state, body = load_heartbeat(mind_dir / "HEARTBEAT.md")
    assert state.cycle == 0
    assert state.trust_tier == "T0"
    assert body == ""


def test_heartbeat_roundtrip_preserves_state(mind_dir: Path):
    path = mind_dir / "HEARTBEAT.md"
    original = HeartbeatState(
        cycle=42,
        session_started_at="2026-05-18T12:00:00+00:00",
        trust_tier="T1",
        status="running",
        model_usage={"anthropic_calls": 3, "openrouter_calls": 7},
        last_drift_score=0.12,
    )
    save_heartbeat(path, original, "narrative body\n")
    state, body = load_heartbeat(path)
    assert state.cycle == 42
    assert state.session_started_at == "2026-05-18T12:00:00+00:00"
    assert state.trust_tier == "T1"
    assert state.status == "running"
    assert state.model_usage == {"anthropic_calls": 3, "openrouter_calls": 7}
    assert state.last_drift_score == 0.12
    assert "narrative body" in body


def test_parse_inbox_extracts_open_and_done_tasks(mind_dir: Path):
    path = mind_dir / "INBOX.md"
    path.write_text(
        "# Inbox\n\n"
        "- [ ] First open task\n"
        "- [x] Already done\n"
        "  - [ ] Indented open task\n"
        "- not a checkbox\n"
        "- [ ] Last open task\n",
        encoding="utf-8",
    )
    tasks = parse_inbox(path)
    assert len(tasks) == 4
    assert tasks[0].text == "First open task" and tasks[0].done is False
    assert tasks[1].text == "Already done" and tasks[1].done is True
    assert tasks[2].text == "Indented open task"
    assert tasks[3].text == "Last open task"


def test_mark_inbox_tasks_done_flips_only_requested_lines(mind_dir: Path):
    path = mind_dir / "INBOX.md"
    path.write_text(
        "- [ ] A\n- [ ] B\n- [x] C\n- [ ] D\n",
        encoding="utf-8",
    )
    tasks = parse_inbox(path)
    target_idx = {t.line_index for t in tasks if t.text in {"A", "D"}}
    flipped = mark_inbox_tasks_done(path, target_idx)
    assert flipped == 2
    after = parse_inbox(path)
    by_text = {t.text: t.done for t in after}
    assert by_text == {"A": True, "B": False, "C": True, "D": True}


# ── loop.py: one cycle ───────────────────────────────────────


@pytest.mark.asyncio
async def test_one_cycle_with_fresh_mind_dir(mind_dir: Path, config: LoopConfig):
    (mind_dir / "INBOX.md").write_text(
        "- [ ] First task\n- [ ] Second task\n", encoding="utf-8"
    )
    report = await ChimeraLoop(config).run_one_cycle()
    assert report.cycle == 1
    assert report.tasks_seen == 2
    assert report.tasks_completed == 0  # ACT is a stub at MVP
    assert report.rotated is False
    # Phase log records all 8 phase markers (HOUSEKEEPING..ROTATE).
    log_text = "\n".join(report.phase_log)
    for phase in ["HOUSEKEEPING", "WAKE", "ASSESS", "PLAN", "ACT", "WRITE", "FLUSH", "COMMIT", "ROTATE"]:
        assert phase in log_text, f"missing phase {phase} in log"


@pytest.mark.asyncio
async def test_cycle_counter_survives_restart(config: LoopConfig):
    """ADR 0003 requires the cycle counter is restored from HEARTBEAT.md frontmatter."""
    loop = ChimeraLoop(config)
    r1 = await loop.run_one_cycle()
    r2 = await loop.run_one_cycle()
    # Simulate "restart" by constructing a new ChimeraLoop instance.
    loop2 = ChimeraLoop(config)
    r3 = await loop2.run_one_cycle()
    assert (r1.cycle, r2.cycle, r3.cycle) == (1, 2, 3)


@pytest.mark.asyncio
async def test_rotate_fires_when_session_exceeds_max_hours(config: LoopConfig, mind_dir: Path):
    # Seed a HEARTBEAT.md that claims the session started 13h ago.
    long_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=13)).isoformat(
        timespec="seconds"
    )
    save_heartbeat(
        mind_dir / "HEARTBEAT.md",
        HeartbeatState(cycle=5, session_started_at=long_ago, status="running"),
        "",
    )
    report = await ChimeraLoop(config).run_one_cycle()
    assert report.rotated is True
    # Post-rotate, session_started_at is cleared so the next cycle starts fresh.
    state, _ = load_heartbeat(mind_dir / "HEARTBEAT.md")
    assert state.session_started_at is None
    assert state.status == "rotated"


@pytest.mark.asyncio
async def test_session_log_appended_each_cycle(config: LoopConfig, mind_dir: Path):
    await ChimeraLoop(config).run_one_cycle()
    await ChimeraLoop(config).run_one_cycle()
    log = (mind_dir / "SESSION_LOG.md").read_text(encoding="utf-8")
    assert "cycle 1 @" in log
    assert "cycle 2 @" in log
