"""Tests for ADR 0094: operator-first ASSESS priority + INBOX provenance.

When engines (Discovery / Curiosity / Reflection) or the Opus planner
append tasks to INBOX.md, those rows are tagged with `<!-- src: X -->`.
ASSESS must sort operator-authored rows (no src tag) ahead of the
agent-proposed ones so engine output never preempts operator intent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import LoopConfig, parse_inbox
from chimera.core.loop import ChimeraLoop


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


def test_parse_inbox_extracts_provenance_tag(mind_dir: Path):
    path = mind_dir / "INBOX.md"
    path.write_text(
        "- [ ] Operator task\n"
        "- [ ] Planner task  <!-- src: planner -->\n"
        "- [ ] Discovery task  <!-- src: discovery -->\n"
        "- [ ] Task with rationale  <!-- because reason -->  <!-- src: curiosity -->\n",
        encoding="utf-8",
    )
    tasks = parse_inbox(path)
    assert [t.source for t in tasks] == [None, "planner", "discovery", "curiosity"]


def test_parse_inbox_no_tag_defaults_to_operator(mind_dir: Path):
    """Backward compat: untagged rows are operator-authored (source=None)."""
    path = mind_dir / "INBOX.md"
    path.write_text("- [ ] Pre-v4.76 row\n", encoding="utf-8")
    [task] = parse_inbox(path)
    assert task.source is None


@pytest.mark.asyncio
async def test_assess_sorts_operator_before_agent_tasks(
    mind_dir: Path, state_dir: Path
):
    """Mixed-provenance INBOX: operator rows first, agent rows after, file order within group."""
    inbox = mind_dir / "INBOX.md"
    inbox.write_text(
        "- [ ] Agent A  <!-- src: planner -->\n"
        "- [ ] Operator 1\n"
        "- [ ] Agent B  <!-- src: discovery -->\n"
        "- [ ] Operator 2\n"
        "- [ ] Agent C  <!-- src: curiosity -->\n",
        encoding="utf-8",
    )
    loop = ChimeraLoop(LoopConfig(mind_dir=mind_dir, state_dir=state_dir))
    from chimera.core.loop import CycleReport
    loop._report = CycleReport(
        cycle=1, started_at="", completed_at="", tasks_seen=0, tasks_completed=0,
    )
    await loop._phase_assess()
    ordered = [t.text for t in loop._tasks]
    # Operator rows first (file order), then agent rows (file order).
    op_idx = [i for i, t in enumerate(loop._tasks) if t.source is None]
    ag_idx = [i for i, t in enumerate(loop._tasks) if t.source is not None]
    assert op_idx and ag_idx
    assert max(op_idx) < min(ag_idx), f"agent task preempted operator: {ordered}"
    operator_texts = [t.text for t in loop._tasks if t.source is None]
    assert operator_texts == ["Operator 1", "Operator 2"]


def test_append_proposals_stamps_provenance(mind_dir: Path, state_dir: Path):
    from dataclasses import dataclass

    @dataclass
    class _P:
        text: str
        rationale: str | None = None

    inbox = mind_dir / "INBOX.md"
    inbox.write_text("- [ ] Operator task\n", encoding="utf-8")
    loop = ChimeraLoop(LoopConfig(mind_dir=mind_dir, state_dir=state_dir))
    loop._append_proposals_to_inbox(
        [_P("Planner task", rationale="because"), _P("Bare planner task")],
        source="planner",
    )
    tasks = parse_inbox(inbox)
    by_text = {t.text.split("  <!--")[0]: t.source for t in tasks}
    assert by_text["Operator task"] is None
    assert by_text["Planner task"] == "planner"
    assert by_text["Bare planner task"] == "planner"


def test_append_proposals_accepts_engine_source(mind_dir: Path, state_dir: Path):
    from dataclasses import dataclass

    @dataclass
    class _P:
        text: str
        rationale: str | None = None

    inbox = mind_dir / "INBOX.md"
    inbox.write_text("", encoding="utf-8")
    loop = ChimeraLoop(LoopConfig(mind_dir=mind_dir, state_dir=state_dir))
    loop._append_proposals_to_inbox([_P("from discovery")], source="discovery")
    [task] = parse_inbox(inbox)
    assert task.source == "discovery"
