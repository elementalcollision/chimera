"""Pre-written contract test for the soak-summary feature (first real target).

Charter: mind/research/soak-summary-design.md. Operator-authored, committed to
main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/soak_summary.py — so these tests pass, WITHOUT touching chimera/cli.py,
chimera/core/soak_ledger.py, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a
clean assertion failure (N failed, never a collection error). Gated by
CHIMERA_V40_GATE.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _table():
    try:
        from chimera.soak_summary import format_iteration_table
    except ImportError as exc:
        pytest.fail(f"chimera.soak_summary.format_iteration_table not importable: {exc}")
    return format_iteration_table


def _summary():
    try:
        from chimera.soak_summary import format_soak_summary
    except ImportError as exc:
        pytest.fail(f"chimera.soak_summary.format_soak_summary not importable: {exc}")
    return format_soak_summary


_HEADER = "| ACT cycle | tool calls | tool errors | tool ms | finish_reason | completed |"
_SEP = "|---:|---:|---:|---:|---|:---:|"

_ROW_A = {"cycle": 146, "tool_call_count": 11, "tool_error_count": 0,
          "tool_total_ms": 1924.0, "finish_reason": "stop", "completed": True}
_ROW_B = {"cycle": 147, "tool_call_count": 14, "tool_error_count": 2,
          "tool_total_ms": 800.5, "finish_reason": "artifact_missing", "completed": False}


# ── format_iteration_table: the test-pinned core ─────────────────

def test_empty_is_empty_string():
    assert _table()([]) == ""


def test_single_row_plus_totals():
    out = _table()([_ROW_A])
    assert out == (
        f"{_HEADER}\n{_SEP}\n"
        "| 146 | 11 | 0 | 1924.0 | stop | Y |\n"
        "| **Σ** | 11 | 0 | 1924.0 | — | — |\n"
    )


def test_two_rows_example_from_charter():
    out = _table()([_ROW_A, _ROW_B])
    assert out == (
        f"{_HEADER}\n{_SEP}\n"
        "| 146 | 11 | 0 | 1924.0 | stop | Y |\n"
        "| 147 | 14 | 2 | 800.5 | artifact_missing | N |\n"
        "| **Σ** | 25 | 2 | 2724.5 | — | — |\n"
    )


def test_completed_renders_Y_N():
    out = _table()([_ROW_B])  # completed False → N
    assert "| 147 | 14 | 2 | 800.5 | artifact_missing | N |" in out
    assert out.endswith("\n")


# ── format_soak_summary: the integration wrapper ─────────────────

def _seed_ledger(mind_dir: Path, run_id: str, rows: list[dict]) -> None:
    import json
    d = mind_dir / "soak" / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "act-tools.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_cli_soak_summary_verb(tmp_path, monkeypatch, capsys):
    # v44 follow-on: the `chimera soak summary <run-id>` CLI wrapper over
    # format_soak_summary (the mind-count leaf pattern). This test is the
    # guard that the verb is actually wired — its absence let an earlier
    # landing ship the module without the CLI verb.
    from chimera.cli import main
    mind = tmp_path / "mind"
    _seed_ledger(mind, "run-cli", [_ROW_A, _ROW_B])
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    rc = main(["soak", "summary", "run-cli"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("# Soak run-cli — 2 ACT cycles\n")
    assert "**Σ**" in out


def test_summary_headline_and_table(tmp_path):
    mind = tmp_path / "mind"
    _seed_ledger(mind, "run-x", [_ROW_A, _ROW_B])
    out = _summary()(mind, "run-x")
    assert out.startswith("# Soak run-x — 2 ACT cycles\n")
    assert _HEADER in out
    assert "| **Σ** | 25 | 2 | 2724.5 | — | — |" in out


def test_summary_empty_ledger(tmp_path):
    mind = tmp_path / "mind"
    out = _summary()(mind, "absent-run")
    assert out == "# Soak absent-run — no ACT records\n"
