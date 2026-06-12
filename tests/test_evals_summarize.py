"""`chimera evals summarize` — the grader-agnostic accuracy gate (ADR 0181).

The "gate" in the gated-nightly: consume a graded JSONL (whatever upstream
grader wrote `is_correct`, per ADR 0135's delegation), aggregate accuracy,
and fail on a threshold miss or baseline regression. Key-free and
provider-agnostic, so this is fully unit-testable without datasets/keys —
which is the point: the gate ships ready before the live nightly's
secrets/budget decisions are made.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from chimera.cli_cmds.evals import _cmd_evals_summarize


def _write_graded(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def _args(**kw) -> argparse.Namespace:
    base = dict(
        graded=None,
        correctness_field="is_correct",
        min_accuracy=None,
        baseline=None,
        tolerance=0.0,
        json=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


# 6 rows: 4 correct → overall 0.6667.
_ROWS = [
    {"category": "single", "is_correct": True},
    {"category": "single", "is_correct": True},
    {"category": "single", "is_correct": False},
    {"category": "multi", "is_correct": True},
    {"category": "multi", "is_correct": True},
    {"category": "multi", "is_correct": False},
]


def test_passes_with_no_gates(tmp_path, capsys):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)
    assert _cmd_evals_summarize(_args(graded=str(g))) == 0
    out = capsys.readouterr().out
    assert "single" in out and "multi" in out


def test_min_accuracy_pass_and_fail(tmp_path):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)  # overall 0.6667
    assert _cmd_evals_summarize(_args(graded=str(g), min_accuracy=0.6)) == 0
    assert _cmd_evals_summarize(_args(graded=str(g), min_accuracy=0.7)) == 1


def test_baseline_regression_fails(tmp_path):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)  # 0.6667
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"_overall": {"accuracy": 0.80}}))
    # Dropped from 0.80 → 0.6667 with zero tolerance ⇒ fail.
    assert _cmd_evals_summarize(
        _args(graded=str(g), baseline=str(baseline))
    ) == 1
    # A generous tolerance absorbs the drop ⇒ pass.
    assert _cmd_evals_summarize(
        _args(graded=str(g), baseline=str(baseline), tolerance=0.2)
    ) == 0


def test_baseline_improvement_passes(tmp_path):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)  # 0.6667
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"_overall": {"accuracy": 0.50}}))
    assert _cmd_evals_summarize(
        _args(graded=str(g), baseline=str(baseline))
    ) == 0


def test_json_output_roundtrips_as_next_baseline(tmp_path, capsys):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)
    assert _cmd_evals_summarize(_args(graded=str(g), json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["_overall"]["total"] == 6
    assert payload["_overall"]["correct"] == 4
    assert abs(payload["_overall"]["accuracy"] - 0.6667) < 1e-4
    # The emitted JSON is consumable as a --baseline next run.
    nb = tmp_path / "nb.json"
    nb.write_text(json.dumps(payload))
    assert _cmd_evals_summarize(_args(graded=str(g), baseline=str(nb))) == 0


def test_custom_correctness_field(tmp_path):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, [
        {"category": "x", "judged_correct": True},
        {"category": "x", "judged_correct": False},
    ])
    # Default field absent → everything counts as incorrect → 0.0 < 0.5.
    assert _cmd_evals_summarize(_args(graded=str(g), min_accuracy=0.5)) == 1
    # Correct field → 0.5, passes the 0.5 floor.
    assert _cmd_evals_summarize(
        _args(graded=str(g), correctness_field="judged_correct", min_accuracy=0.5)
    ) == 0


def test_missing_graded_file_returns_2(tmp_path):
    assert _cmd_evals_summarize(_args(graded=str(tmp_path / "nope.jsonl"))) == 2


def test_empty_graded_file_returns_2(tmp_path):
    g = tmp_path / "empty.jsonl"
    g.write_text("")
    assert _cmd_evals_summarize(_args(graded=str(g))) == 2


def test_missing_baseline_file_returns_2(tmp_path):
    g = tmp_path / "graded.jsonl"
    _write_graded(g, _ROWS)
    assert _cmd_evals_summarize(
        _args(graded=str(g), baseline=str(tmp_path / "nobase.json"))
    ) == 2
