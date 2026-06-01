"""v4.59 (ADR 0078) — pre-flight cost estimation."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.cost_estimate import (
    estimate_inbox,
    estimate_task_cost,
)
from chimera.core.escalation import record_failure
from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _write_inbox(p: Path, lines: list[str]) -> Path:
    p.write_text("# Inbox\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


# ── single-task projections ───────────────────────────────────────


def test_no_history_falls_back_to_tier_typical(db):
    """No api_calls rows → uses tier-typical token estimate × prices."""
    est = estimate_task_cost(db, "Add a widget at (0, 16, 4, 4)")
    # default_tier=haiku, no research keywords → tier="haiku"
    assert est.tier == "haiku"
    # After v4.53 ladder inversion, "haiku" → deepseek-v4-flash.
    assert est.model_id == "openai/gpt-5-nano"
    assert est.used_history is False
    assert est.n_historical_cycles == 0
    assert est.estimated_cycles == 1
    # 8000 input × $0.14/Mtok + 1500 output × $0.28/Mtok = $0.00112 + $0.00042
    assert est.estimated_usd == pytest.approx(0.0010, abs=0.0002)


def test_research_text_floors_to_sonnet(db):
    """Research keywords → tier="sonnet" → deepseek-v4-pro rung."""
    est = estimate_task_cost(
        db, "Research and write a citation-heavy section from peer-reviewed sources",
    )
    assert est.tier == "sonnet"
    assert est.model_id == "deepseek/deepseek-v4-pro"
    # Should be more expensive than the haiku case.
    assert est.estimated_usd > 0.005


def test_history_overrides_fallback(db):
    """When api_calls has cycles for the target model, use the median."""
    # Three cycles on the haiku rung-0 model, varying spend.
    for cycle, in_tok in zip((1, 2, 3), (1_000_000, 2_000_000, 3_000_000)):
        record_api_call(
            db, cycle=cycle, provider="openrouter",
            model_id="openai/gpt-5-nano",
            input_tokens=in_tok, output_tokens=0,
        )
    db.commit()
    est = estimate_task_cost(db, "Refactor the loop body")
    assert est.used_history is True
    assert est.n_historical_cycles == 3
    # Median = 2M tokens × $0.14/Mtok = $0.28.
    assert est.estimated_usd == pytest.approx(0.10, abs=0.001)


def test_prior_failures_increase_cycles(db):
    """One prior failure → +1 cycle baseline. Memory also promotes tier."""
    text = "Dashboard honesty audit — spawn sub-agents and compile"
    record_failure(db, task_text=text, tier="haiku", finish_reason="max_rounds",
                   rounds_used=20, cycle=10)
    est = estimate_task_cost(db, text)
    # Memory says haiku failed → promote to sonnet.
    assert est.tier == "sonnet"
    # 1 prior failure → 2 estimated cycles.
    assert est.estimated_cycles == 2
    assert est.prior_failures == 1


# ── inbox-level rollup ────────────────────────────────────────────


def test_inbox_empty(tmp_path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [])
    report = estimate_inbox(db, inbox)
    assert report.n_tasks == 0
    assert report.total_usd == 0.0
    assert report.tasks == []


def test_inbox_skips_done_tasks(tmp_path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [x] Already done — should not count",
        "- [ ] Open task — counts",
    ])
    report = estimate_inbox(db, inbox)
    assert report.n_tasks == 1
    assert len(report.tasks) == 1


def test_inbox_sums_across_tasks(tmp_path, db):
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] Refactor module A",
        "- [ ] Refactor module B",
        "- [ ] Research and write a citation-heavy section from peer-reviewed sources",
    ])
    report = estimate_inbox(db, inbox)
    assert report.n_tasks == 3
    # Total ≥ sum of each individual task's lower-bound projection.
    assert report.total_usd > 0
    # Total cycles ≥ 3 (one per task minimum).
    assert report.total_cycles >= 3
    # Research task should be more expensive than refactor tasks.
    research = [t for t in report.tasks if "research" in t.task_text.lower()]
    refactor = [t for t in report.tasks if "refactor" in t.task_text.lower()]
    assert research and refactor
    assert research[0].estimated_usd > refactor[0].estimated_usd


def test_overnight_burn_replay(tmp_path, db):
    """Replay a synthetic INBOX with the same shape that caused the
    2026-05-19 burn. Total projection should be small (deepseek rungs),
    nowhere near the $231 actually burned — proving the v4.53 ladder
    inversion changes the projection too, not just the runtime cost."""
    inbox = _write_inbox(tmp_path / "INBOX.md", [
        "- [ ] Dashboard honesty audit — spawn 14 sub-agents and compile findings",
        "- [ ] Research and write the four missing sections citing peer-reviewed sources",
        "- [ ] Code review of two modules",
    ])
    report = estimate_inbox(db, inbox)
    # No history → falls back to tier-typical estimates. With the v4.53
    # ladder, even research-floored opus-tier tasks route through
    # deepseek-v4-pro. Projection should stay well under $5 total.
    assert report.total_usd < 5.0
    # But > $0.01 (it's not free).
    assert report.total_usd > 0.01
