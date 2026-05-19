"""Tests for v4.15 drift_log."""

from __future__ import annotations

from pathlib import Path

from chimera.core.drift_log import list_drift, record_drift


def test_record_and_list_drift_round_trip(tmp_path: Path):
    log = tmp_path / "drift.jsonl"
    record_drift(
        cycle=3, composite_score=0.27, severity="medium",
        action="warn_only", reason="composite ≥ warning threshold",
        path=log,
    )
    record_drift(
        cycle=4, composite_score=0.42, severity="high",
        action="demote_plan", reason="composite ≥ lockdown",
        path=log,
    )
    rows = list_drift(path=log)
    assert [r.cycle for r in rows] == [3, 4]
    assert rows[0].composite_score == 0.27
    assert rows[1].severity == "high"
    assert rows[1].action == "demote_plan"


def test_list_drift_limit(tmp_path: Path):
    log = tmp_path / "drift.jsonl"
    for cycle in range(5):
        record_drift(
            cycle=cycle, composite_score=0.1 * cycle, severity="low",
            action="noop", reason="x", path=log,
        )
    rows = list_drift(path=log, limit=2)
    assert [r.cycle for r in rows] == [3, 4]


def test_list_drift_empty_returns_empty(tmp_path: Path):
    assert list_drift(path=tmp_path / "missing.jsonl") == []


def test_list_drift_tolerates_malformed_lines(tmp_path: Path):
    log = tmp_path / "drift.jsonl"
    log.write_text(
        '{"cycle": 1, "composite_score": 0.1, "severity": "low", '
        '"action": "noop", "reason": "x", "recorded_at": "now"}\n'
        '{not json}\n'
        '\n'
        '{"cycle": 2, "composite_score": 0.2, "severity": "low", '
        '"action": "noop", "reason": "x", "recorded_at": "now"}\n',
        encoding="utf-8",
    )
    rows = list_drift(path=log)
    assert [r.cycle for r in rows] == [1, 2]
