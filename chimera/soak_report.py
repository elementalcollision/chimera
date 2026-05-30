"""Soak-report module composing soak_summary and soak_breakdown.

Two public functions:
- format_report_body(act_rows): composes iteration table + finish-reason breakdown.
- format_soak_report(mind_dir, run_id): reads ledger from disk, formats full report.

Provenance: authored by Chimera autonomously during the v46 soak — the THIRD
real feature (capstone of the soak-analysis trio; the first build to import
existing Chimera modules). Branch chimera-soak/v46-soakreport-2026-05-30-1812.
The v46 soak was PARTIAL — the module was written and tested green (4/4) but
phase 2 stalled without committing; operator-landed here. The run confirmed the
three friction fixes in-loop (0 witness_rejected, 0 dishonest, churn fix held)
and surfaced the next defect (phase-2 commit stall) — see
mind/research/v46-soakreport-capstone.md. Exposed via `chimera soak report`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chimera.soak_summary import format_iteration_table
from chimera.soak_breakdown import format_finish_reason_breakdown
from chimera.core.soak_ledger import _read_jsonl


def format_report_body(act_rows: list[dict[str, Any]]) -> str:
    """Return a markdown report body composing iteration table + finish-reason breakdown."""
    if not act_rows:
        return ""
    return "## Iterations\n\n" + format_iteration_table(act_rows) + "\n## Finish reasons\n\n" + format_finish_reason_breakdown(act_rows)


def format_soak_report(
    mind_dir: Path | str,
    run_id: str,
) -> str:
    """Read a soak run's ACT-tools ledger and return a full report."""
    path = Path(mind_dir) / "soak" / run_id / "act-tools.jsonl"
    rows = _read_jsonl(path)
    if not rows:
        return f"# Soak {run_id} — no ACT records\n"
    n = len(rows)
    return f"# Soak {run_id} — report ({n} cycles)\n\n" + format_report_body(rows)
