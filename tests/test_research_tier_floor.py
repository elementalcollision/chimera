"""v4.56 (ADR 0075) — research-task tier floor.

The 2026-05-19 escalation postmortem found that haiku consistently
fails research-shaped tasks (web_search + http_fetch + citation
weaving + file writing in one cycle). The 1952-character "research
and write FOUR sections" task burnt rounds on tool sequencing
before reaching substantive output. The remediation: detect the
shape and floor the tier at sonnet so the first attempt has a
fighting chance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import recommended_tier, research_task_floor_tier
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


# ── pure heuristic ────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Research and write a 4-section analysis citing peer-reviewed sources",
    "Compile findings from peer reviewed literature on …",
    "Cite inline using (Author, Year). Use academic literature only.",
    "Research and synthesize three named-journalism pieces.",
    "Find at least 5 citations from academic literature.",
])
def test_research_keywords_trigger_sonnet_floor(text):
    assert research_task_floor_tier(text) == "sonnet"


@pytest.mark.parametrize("text", [
    "Use shell to cat a file",
    "Add a widget at (x,y) in CanvasShell",
    "Refactor the loop body",
    "",
])
def test_non_research_returns_none(text):
    assert research_task_floor_tier(text) is None


# ── integration with recommended_tier ─────────────────────────────


def test_recommended_tier_floors_research_at_sonnet(db):
    """Empty memory + research task + default haiku → sonnet."""
    text = "Research and write a section citing peer-reviewed sources"
    assert recommended_tier(db, task_text=text, default_tier="haiku") == "sonnet"


def test_recommended_tier_preserves_higher_default(db):
    """If caller already supplied sonnet/opus, the floor doesn't demote."""
    text = "Research and cite inline from peer-reviewed sources"
    assert recommended_tier(db, task_text=text, default_tier="opus") == "opus"


def test_recommended_tier_haiku_unchanged_for_non_research(db):
    """No research keywords → default tier survives."""
    text = "Add a widget at (x=0, y=16, w=4, h=4) in app/page.tsx"
    assert recommended_tier(db, task_text=text, default_tier="haiku") == "haiku"


def test_research_floor_combines_with_escalation_memory(db):
    """Research floor + prior sonnet failure → promote to opus, not back to sonnet."""
    from chimera.core.escalation import record_failure
    text = "Research and write a peer-reviewed citation section"
    # Prior sonnet failure on a similar signature.
    record_failure(db, task_text=text, tier="sonnet", finish_reason="max_rounds",
                   rounds_used=20, cycle=10)
    # Should promote: sonnet (failed) → opus. Floor of sonnet doesn't block this.
    assert recommended_tier(db, task_text=text, default_tier="haiku") == "opus"


def test_research_floor_holds_against_prior_haiku_failure(db):
    """Research floor at sonnet + prior haiku failure shouldn't degrade
    promotion path: prior haiku failure normally → sonnet, which matches
    the floor. End result: sonnet."""
    from chimera.core.escalation import record_failure
    text = "Research and write citing peer-reviewed sources"
    record_failure(db, task_text=text, tier="haiku", finish_reason="max_rounds",
                   rounds_used=20, cycle=10)
    # Memory says: haiku failed → sonnet. Floor says: sonnet. Both agree.
    assert recommended_tier(db, task_text=text, default_tier="haiku") == "sonnet"
