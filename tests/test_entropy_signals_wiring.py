"""ADR 0170 wiring: per-cycle tool-use entropy emitted from _phase_act.

The pure signals (tests/test_entropy_signals.py) were landed by PR #276 but
no live-loop caller consumed them — the routing soak campaign flagged the
module as dead wiring. These tests pin the loop-side consumer: with
CHIMERA_ENTROPY_SIGNALS on, the ACT phase logs the cycle's tool-use entropy
and records it in the activity details; with the flag off (default) the
phase log and activity details are byte-identical to the prior path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.core.loop import ChimeraLoop, LoopConfig
from chimera.tools.loop_guard import ToolCall


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


class _ToolUsingFakeAct:
    """ACT double whose result carries a scripted tool_call_history."""

    def __init__(self, tool_names: list[str]) -> None:
        self.providers = []
        self._chronicle = None
        self._tool_names = tool_names

    async def execute(self, task_text, *, cycle, context=None):
        from chimera.core.act import ActResult

        return ActResult(
            task_text=task_text,
            completed=True,
            rounds=1,
            finish_reason="stop",
            tool_call_history=[
                ToolCall(name=n, args={}) for n in self._tool_names
            ],
        )


def _promote_trust(loop) -> None:
    from chimera.trust import TrustTier

    loop._trust._state.current_tier = int(TrustTier.T3)


def _act_details(loop) -> dict:
    row = loop.db.execute(
        "SELECT details FROM agent_activity_log WHERE cell_id = 'act' "
        "ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "no act activity row recorded"
    return json.loads(row["details"])


@pytest.mark.asyncio
async def test_entropy_signal_emitted_when_flag_on(
    config: LoopConfig, mind_dir: Path, monkeypatch,
):
    monkeypatch.setenv("CHIMERA_ENTROPY_SIGNALS", "1")
    (mind_dir / "INBOX.md").write_text("- [ ] a task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    # Two distinct tools, evenly used → normalized entropy 1.0.
    loop._act = _ToolUsingFakeAct(["shell", "web_fetch", "shell", "web_fetch"])
    _promote_trust(loop)

    report = await loop.run_one_cycle()

    log_text = "\n".join(report.phase_log)
    assert "tool-use entropy H=1.0 over 4 tool call(s)" in log_text
    details = _act_details(loop)
    assert details["tool_entropy"] == 1.0
    assert details["tool_calls"] == 4
    loop.close()


@pytest.mark.asyncio
async def test_entropy_signal_fixation_reads_low(
    config: LoopConfig, mind_dir: Path, monkeypatch,
):
    """All calls on one tool → H=0.0, the fixation precursor ADR 0170 names."""
    monkeypatch.setenv("CHIMERA_ENTROPY_SIGNALS", "1")
    (mind_dir / "INBOX.md").write_text("- [ ] a task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    loop._act = _ToolUsingFakeAct(["shell", "shell", "shell", "shell"])
    _promote_trust(loop)

    report = await loop.run_one_cycle()

    assert "tool-use entropy H=0.0 over 4 tool call(s)" in "\n".join(
        report.phase_log
    )
    assert _act_details(loop)["tool_entropy"] == 0.0
    loop.close()


@pytest.mark.asyncio
async def test_flag_unset_emits_by_default(
    config: LoopConfig, mind_dir: Path, monkeypatch,
):
    """ADR 0180: ENTROPY_SIGNALS is default-ON — an unset env emits the
    entropy signal (registry-default read, ADR 0179 mechanism)."""
    monkeypatch.delenv("CHIMERA_ENTROPY_SIGNALS", raising=False)
    (mind_dir / "INBOX.md").write_text("- [ ] a task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    loop._act = _ToolUsingFakeAct(["shell", "web_fetch"])
    _promote_trust(loop)

    report = await loop.run_one_cycle()

    assert "tool-use entropy" in "\n".join(report.phase_log)
    assert "tool_entropy" in _act_details(loop)
    loop.close()


@pytest.mark.asyncio
async def test_flag_disabled_is_byte_identical(
    config: LoopConfig, mind_dir: Path, monkeypatch,
):
    """Explicit disable (=0) restores the pre-ADR-0170 emission shape —
    the opt-out contract for the default-ON graduation."""
    monkeypatch.setenv("CHIMERA_ENTROPY_SIGNALS", "0")
    (mind_dir / "INBOX.md").write_text("- [ ] a task\n", encoding="utf-8")
    loop = ChimeraLoop(config)
    loop._act = _ToolUsingFakeAct(["shell", "web_fetch"])
    _promote_trust(loop)

    report = await loop.run_one_cycle()

    assert "tool-use entropy" not in "\n".join(report.phase_log)
    details = _act_details(loop)
    assert "tool_entropy" not in details
    assert "tool_calls" not in details
    # The prior keys are unchanged.
    assert set(details) == {"tasks", "completed", "api_calls"}
    loop.close()
