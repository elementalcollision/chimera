"""Pre-written contract test for the v46 soak-report feature (trio capstone).

Charter: mind/research/v46-soakreport-design.md. Operator-authored, committed to
main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/soak_report.py — composing the two existing pure cores
(chimera.soak_summary.format_iteration_table + chimera.soak_breakdown.
format_finish_reason_breakdown) so these tests pass, WITHOUT modifying those
modules, chimera/cli.py, chimera/core/soak_ledger.py, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a clean
assertion failure. Gated by CHIMERA_V40_GATE.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _body():
    try:
        from chimera.soak_report import format_report_body
    except ImportError as exc:
        pytest.fail(f"chimera.soak_report.format_report_body not importable: {exc}")
    return format_report_body


def _report():
    try:
        from chimera.soak_report import format_soak_report
    except ImportError as exc:
        pytest.fail(f"chimera.soak_report.format_soak_report not importable: {exc}")
    return format_soak_report


# Rows shaped like the real ledger (cycle + the fields the two cores read).
_ROWS = [
    {"cycle": 1, "tool_call_count": 5, "tool_error_count": 0,
     "tool_total_ms": 10.0, "finish_reason": "stop", "completed": True},
    {"cycle": 2, "tool_call_count": 3, "tool_error_count": 1,
     "tool_total_ms": 4.0, "finish_reason": "stop", "completed": True},
]


def _expected_body():
    # Compose the two existing cores' exact outputs (the contract).
    from chimera.soak_breakdown import format_finish_reason_breakdown
    from chimera.soak_summary import format_iteration_table
    iter_table = format_iteration_table(_ROWS)
    breakdown = format_finish_reason_breakdown(_ROWS)
    return "## Iterations\n\n" + iter_table + "\n## Finish reasons\n\n" + breakdown


# ── format_report_body: the test-pinned core ─────────────────────

def test_empty_is_empty_string():
    assert _body()([]) == ""


def test_body_composes_both_sections():
    out = _body()(_ROWS)
    assert out == _expected_body()
    assert "## Iterations" in out
    assert "## Finish reasons" in out
    assert "| finish_reason | count |" in out


# ── format_soak_report: the integration wrapper ──────────────────

def _seed(mind_dir: Path, run_id: str, rows: list[dict]) -> None:
    import json
    d = mind_dir / "soak" / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "act-tools.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_report_headline_and_body(tmp_path):
    mind = tmp_path / "mind"
    _seed(mind, "run-r", _ROWS)
    out = _report()(mind, "run-r")
    assert out == "# Soak run-r — report (2 cycles)\n\n" + _expected_body()


def test_report_empty_ledger(tmp_path):
    mind = tmp_path / "mind"
    out = _report()(mind, "absent")
    assert out == "# Soak absent — no ACT records\n"


def test_cli_soak_report_verb(tmp_path, monkeypatch, capsys):
    # CLI guard (the #169/#170 lesson): the verb is actually wired.
    from chimera.cli import main
    mind = tmp_path / "mind"
    _seed(mind, "run-cli", _ROWS)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    rc = main(["soak", "report", "run-cli"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("# Soak run-cli — report (2 cycles)\n\n")
    assert "## Iterations" in out and "## Finish reasons" in out
