"""Pre-written contract test for the v45 soak-breakdown feature.

Charter: mind/research/v45-soakbreakdown-design.md. Operator-authored, committed
to main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/soak_breakdown.py — so these tests pass, WITHOUT touching chimera/cli.py,
chimera/core/soak_ledger.py, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a clean
assertion failure (N failed, never a collection error). Gated by CHIMERA_V40_GATE.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CHIMERA_V40_GATE"),
    reason="v45 build-capability gate; run with CHIMERA_V40_GATE=1",
)


def _breakdown():
    try:
        from chimera.soak_breakdown import format_finish_reason_breakdown
    except ImportError as exc:
        pytest.fail(f"chimera.soak_breakdown.format_finish_reason_breakdown not importable: {exc}")
    return format_finish_reason_breakdown


def _soak():
    try:
        from chimera.soak_breakdown import format_soak_breakdown
    except ImportError as exc:
        pytest.fail(f"chimera.soak_breakdown.format_soak_breakdown not importable: {exc}")
    return format_soak_breakdown


_HEADER = "| finish_reason | count |"
_SEP = "|---|---:|"


def _rows(*reasons: str) -> list[dict]:
    return [{"cycle": i, "finish_reason": r} for i, r in enumerate(reasons)]


# ── format_finish_reason_breakdown: the test-pinned core ─────────

def test_empty_is_empty_string():
    assert _breakdown()([]) == ""


def test_single_reason_plus_total():
    out = _breakdown()(_rows("stop"))
    assert out == f"{_HEADER}\n{_SEP}\n| stop | 1 |\n| **Σ** | 1 |\n"


def test_sorted_by_count_desc():
    out = _breakdown()(_rows("stop", "stop", "artifact_missing", "stop"))
    assert out == (
        f"{_HEADER}\n{_SEP}\n"
        "| stop | 3 |\n"
        "| artifact_missing | 1 |\n"
        "| **Σ** | 4 |\n"
    )


def test_ties_broken_by_reason_ascending():
    # two reasons each count 1 → alphabetical: artifact_missing before stop.
    out = _breakdown()(_rows("stop", "artifact_missing"))
    assert out == (
        f"{_HEADER}\n{_SEP}\n"
        "| artifact_missing | 1 |\n"
        "| stop | 1 |\n"
        "| **Σ** | 2 |\n"
    )


# ── format_soak_breakdown: the integration wrapper ───────────────

def _seed(mind_dir: Path, run_id: str, rows: list[dict]) -> None:
    import json
    d = mind_dir / "soak" / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "act-tools.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_soak_breakdown_headline_and_table(tmp_path):
    mind = tmp_path / "mind"
    _seed(mind, "run-b", _rows("stop", "stop", "artifact_missing"))
    out = _soak()(mind, "run-b")
    assert out.startswith("# Soak run-b — finish-reason breakdown (3 cycles)\n")
    assert _HEADER in out
    assert "| stop | 2 |" in out


def test_soak_breakdown_empty_ledger(tmp_path):
    mind = tmp_path / "mind"
    out = _soak()(mind, "absent")
    assert out == "# Soak absent — no ACT records\n"
