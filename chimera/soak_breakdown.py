"""Finish-reason breakdown table for soak-run postmortems.

Two public functions:

- :func:`format_finish_reason_breakdown` -- pure, counts finish_reason
  values and returns a markdown table sorted by COUNT DESCENDING then
  reason ASCENDING.
- :func:`format_soak_breakdown` -- reads a soak ledger from disk and returns
  a headline + the breakdown table.

Provenance: authored by Chimera autonomously during the v45 soak — the SECOND
real feature (after v44's soak_summary). Branch
chimera-soak/v45-soakbreakdown-2026-05-30-1654, agent commit 6b1ade6. Landed
verbatim + this note. v45 also validated three build-soak fixes in-loop
(over-claim #168, artifact-detail #173, witness asymmetric #174) and the #173
instrumentation diagnosed the long-standing postmortem churn (see
mind/research/v45-soakbreakdown-capstone.md). Exposed via `chimera soak breakdown`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chimera.core.soak_ledger import _read_jsonl

_HEADER = "| finish_reason | count |"
_SEP = "|---|---:|"


def format_finish_reason_breakdown(act_rows: list[dict[str, Any]]) -> str:
    """Return a markdown table of finish_reason frequencies.

    Sorted by COUNT descending, then reason ascending.
    """
    if not act_rows:
        return ""

    from collections import Counter

    counts = Counter(row["finish_reason"] for row in act_rows)

    # Sort: count DESC, then reason ASC
    sorted_reasons = sorted(counts, key=lambda r: (-counts[r], r))

    lines = [_HEADER, _SEP]
    total = 0
    for reason in sorted_reasons:
        cnt = counts[reason]
        lines.append(f"| {reason} | {cnt} |")
        total += cnt
    lines.append(f"| **\u03a3** | {total} |")
    return "\n".join(lines) + "\n"


def format_soak_breakdown(
    mind_dir: Path | str,
    run_id: str,
) -> str:
    """Read a soak run's ACT-tools ledger and return the finish-reason breakdown.

    Returns a string starting with a headline and containing the breakdown table,
    or a "no ACT records" message when the ledger is empty/missing.
    """
    path = Path(mind_dir) / "soak" / run_id / "act-tools.jsonl"
    rows = _read_jsonl(path)
    if not rows:
        return f"# Soak {run_id} — no ACT records\n"
    n = len(rows)
    headline = f"# Soak {run_id} — finish-reason breakdown ({n} cycles)"
    return headline + "\n" + format_finish_reason_breakdown(rows)
