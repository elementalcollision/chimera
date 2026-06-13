"""Production-health rollup (`chimera health` core, ADR 0182 Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.drift_log import record_drift
from chimera.core.escalation import record_failure
from chimera.core.health import compute_health
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _status(summary, key):
    return next(d.status for d in summary.dimensions if d.key == key)


def test_clean_db_is_healthy(db, tmp_path):
    s = compute_health(db, drift_path=tmp_path / "none.jsonl")
    assert s.overall == "green"
    # No spend / no drift records → unknown, which never drags the verdict.
    assert _status(s, "cost") == "unknown"
    assert _status(s, "drift") == "unknown"
    assert _status(s, "queue") == "green"
    assert _status(s, "escalations") == "green"


def test_high_severity_drift_is_red(db, tmp_path):
    dl = tmp_path / "drift.jsonl"
    record_drift(cycle=5, composite_score=0.9, severity="high",
                 action="demote", reason="x", path=dl)
    s = compute_health(db, drift_path=dl)
    assert _status(s, "drift") == "red"
    assert s.overall == "red"


def test_low_severity_drift_is_green(db, tmp_path):
    dl = tmp_path / "drift.jsonl"
    record_drift(cycle=5, composite_score=0.1, severity="low",
                 action="none", reason="x", path=dl)
    s = compute_health(db, drift_path=dl)
    assert _status(s, "drift") == "green"
    assert s.overall == "green"


def test_latest_drift_record_wins(db, tmp_path):
    dl = tmp_path / "drift.jsonl"
    record_drift(cycle=1, composite_score=0.9, severity="high",
                 action="demote", reason="old", path=dl)
    record_drift(cycle=2, composite_score=0.1, severity="low",
                 action="none", reason="recovered", path=dl)
    s = compute_health(db, drift_path=dl)
    assert _status(s, "drift") == "green"  # the recent low record, not the old high


def test_hot_signatures_are_amber(db, tmp_path):
    # Two failures on the same signature → a hot signature.
    for _ in range(2):
        record_failure(
            db, task_text="fix the recurring frobnicator bug in module x",
            tier="sonnet", finish_reason="artifact_incomplete",
            rounds_used=8, cycle=3,
        )
    s = compute_health(db, drift_path=tmp_path / "none.jsonl")
    assert _status(s, "escalations") == "amber"
    assert s.overall == "amber"


def test_worst_of_overall(db, tmp_path):
    # Amber escalations + red drift → overall red (worst-of).
    for _ in range(2):
        record_failure(
            db, task_text="recurring failure signature alpha beta gamma",
            tier="opus", finish_reason="artifact_incomplete",
            rounds_used=8, cycle=3,
        )
    dl = tmp_path / "drift.jsonl"
    record_drift(cycle=9, composite_score=0.95, severity="critical",
                 action="lockdown", reason="x", path=dl)
    s = compute_health(db, drift_path=dl)
    assert _status(s, "escalations") == "amber"
    assert _status(s, "drift") == "red"
    assert s.overall == "red"


def test_to_dict_shape(db, tmp_path):
    d = compute_health(db, drift_path=tmp_path / "none.jsonl").to_dict()
    assert d["overall"] in {"green", "amber", "red", "unknown"}
    assert {dim["key"] for dim in d["dimensions"]} == {
        "cost", "drift", "queue", "escalations"
    }
