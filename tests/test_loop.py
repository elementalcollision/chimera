"""Tests for the 8-phase Chimera loop (ACT stubbed)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
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


def test_parse_inbox_joins_wrapped_continuation_lines(mind_dir: Path):
    """v4.81 regression: a wrapped bullet whose continuation lines are
    indented deeper than the marker must fold into one task. Soak v3
    surfaced this: the path lived on the second line and ACT's NL
    artifact regex (ADR 0093) never saw it because parse_inbox only
    returned the first line.
    """
    path = mind_dir / "INBOX.md"
    path.write_text(
        "- [ ] Write all of the above to\n"
        "  `mind/research/loop-abort-investigation.md`. The file MUST end\n"
        "  with a section whose heading is EXACTLY:\n"
        "  `## READY-FOR-REMEDIATION`\n"
        "\n"
        "- [ ] Next task\n",
        encoding="utf-8",
    )
    tasks = parse_inbox(path)
    assert len(tasks) == 2
    assert tasks[0].text.startswith("Write all of the above to\n")
    assert "`mind/research/loop-abort-investigation.md`" in tasks[0].text
    assert "READY-FOR-REMEDIATION" in tasks[0].text
    assert tasks[1].text == "Next task"


def test_parse_inbox_continuation_does_not_swallow_dedented_lines(mind_dir: Path):
    path = mind_dir / "INBOX.md"
    path.write_text(
        "- [ ] First bullet\n"
        "  with continuation\n"
        "not a continuation, dedented to col 0\n"
        "- [ ] Second bullet\n",
        encoding="utf-8",
    )
    tasks = parse_inbox(path)
    assert len(tasks) == 2
    assert tasks[0].text == "First bullet\nwith continuation"
    assert tasks[1].text == "Second bullet"


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
    # Every phase recorded a non-negative wall-clock time.
    expected_keys = {
        "housekeeping", "wake", "assess", "plan", "act",
        "write", "flush", "commit", "rotate",
    }
    assert expected_keys <= set(report.phase_times_ms.keys())
    assert all(v >= 0 for v in report.phase_times_ms.values())


@pytest.mark.asyncio
async def test_engines_kill_switch_gates_plan_phase(
    config: LoopConfig, monkeypatch,
):
    """v4.12 / L-4: CHIMERA_ENGINES_ENABLED=0 must skip both the daily
    engines AND the Opus planner. Prior to v4.12 the planner leaked
    through on every-Nth-cycle ticks."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    # Force every-Nth alignment so the planner would normally fire.
    config.opus_plan_every_n_cycles = 1
    report = await ChimeraLoop(config).run_one_cycle()
    log_text = "\n".join(report.phase_log)
    assert "PLAN: skipped (engines disabled)" in log_text
    assert report.phase_times_ms.get("plan", 0) < 100  # no model calls
    assert report.proposals_added == 0


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


# ── ACT-phase budget enforcement (v35 postmortem ladder #4) ─────────


class _SlowFakeAct:
    """ACT executor double that sleeps past any reasonable budget."""

    def __init__(self, sleep_seconds: float = 5.0) -> None:
        self._sleep_seconds = sleep_seconds
        self.providers = []
        self._chronicle = None
        self.invocations = 0

    async def execute(self, task_text, *, cycle, context=None):
        self.invocations += 1
        await asyncio.sleep(self._sleep_seconds)
        from chimera.core.act import ActResult
        return ActResult(
            task_text=task_text, completed=True, rounds=1,
            finish_reason="stop",
        )


class _FastFakeAct:
    """ACT executor double that returns immediately."""

    def __init__(self) -> None:
        self.providers = []
        self._chronicle = None
        self.invocations = 0

    async def execute(self, task_text, *, cycle, context=None):
        self.invocations += 1
        from chimera.core.act import ActResult
        return ActResult(
            task_text=task_text, completed=True, rounds=1,
            finish_reason="stop",
        )


def _promote_trust_for_test(loop) -> None:
    """Lift trust out of T0 so _phase_act will actually dispatch."""
    from chimera.trust import TrustTier
    loop._trust._state.current_tier = int(TrustTier.T3)


@pytest.mark.asyncio
async def test_act_budget_cancels_at_threshold(
    config: LoopConfig, mind_dir: Path, monkeypatch, caplog,
):
    """v35 postmortem ladder #4: when ACT exceeds CHIMERA_ACT_BUDGET_SECONDS
    the in-flight executor is cancelled and the loop advances. Without
    enforcement the v35 soak ran ACT 8.4× over the 240s budget."""
    monkeypatch.setenv("CHIMERA_ACT_BUDGET_SECONDS", "0.05")
    (mind_dir / "INBOX.md").write_text("- [ ] long-running task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    loop._act = _SlowFakeAct(sleep_seconds=5.0)
    _promote_trust_for_test(loop)

    caplog.set_level(logging.WARNING, logger="chimera.core.loop")
    report = await asyncio.wait_for(loop.run_one_cycle(), timeout=2.0)

    # Loop completed despite over-budget ACT.
    assert report.cycle == 1
    # ACT did not run unbounded — well under the slow fake's 5s sleep.
    assert report.phase_times_ms["act"] < 1500
    # Structured budget event surfaced.
    budget_events = [
        r for r in caplog.records
        if getattr(r, "event", None) == "act_budget_exceeded"
    ]
    assert budget_events, "expected an act_budget_exceeded structured log"
    assert budget_events[0].budget_seconds == pytest.approx(0.05)
    # Subsequent phases still ran.
    log_text = "\n".join(report.phase_log)
    assert "WRITE" in log_text
    assert "COMMIT" in log_text


@pytest.mark.asyncio
async def test_act_phase_in_budget_passes_through(
    config: LoopConfig, mind_dir: Path, monkeypatch, caplog,
):
    """ACT calls that finish under budget run uninterrupted and emit no
    act_budget_exceeded event."""
    monkeypatch.setenv("CHIMERA_ACT_BUDGET_SECONDS", "10")
    (mind_dir / "INBOX.md").write_text("- [ ] quick task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    fast = _FastFakeAct()
    loop._act = fast
    _promote_trust_for_test(loop)

    caplog.set_level(logging.WARNING, logger="chimera.core.loop")
    report = await loop.run_one_cycle()

    assert fast.invocations == 1
    assert report.phase_times_ms["act"] < 500
    assert not [
        r for r in caplog.records
        if getattr(r, "event", None) == "act_budget_exceeded"
    ]


def test_act_budget_seconds_env_default(monkeypatch):
    """Default budget honours the v35 postmortem's 240s baseline; explicit
    operator override is preserved verbatim."""
    from chimera.core.loop import _act_budget_seconds
    monkeypatch.delenv("CHIMERA_ACT_BUDGET_SECONDS", raising=False)
    assert _act_budget_seconds() == 240.0
    monkeypatch.setenv("CHIMERA_ACT_BUDGET_SECONDS", "120")
    assert _act_budget_seconds() == 120.0
    monkeypatch.setenv("CHIMERA_ACT_BUDGET_SECONDS", "nonsense")
    assert _act_budget_seconds() == 240.0
