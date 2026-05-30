"""Soak-run summary formatting for postmortems.

This module provides two public functions:

- :func:`format_iteration_table` — pure, transforms a list of ACT-cycle
  records into a markdown table with a totals row.
- :func:`format_soak_summary` — reads a soak ledger from disk and returns
  a complete summary string.

Provenance: authored by Chimera autonomously during the v44 soak — the FIRST
real feature target after the build-capability ladder (v40′→v43). Branch
chimera-soak/v44-soaksummary-2026-05-30-1400, agent commit 1684be4. Landed
verbatim + this provenance note. The v44 run also surfaced and validated the
over-claim-only honesty-gate fix (mind/research/
v44-honesty-gate-moving-target-diagnosis.md); convergence record
mind/research/v44-soaksummary-capstone.md. Exposed via `chimera soak summary`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chimera.core.soak_ledger import _read_jsonl

_HEADER = "| ACT cycle | tool calls | tool errors | tool ms | finish_reason | completed |"
_SEP = "|---:|---:|---:|---:|---|:---:|"


def format_iteration_table(act_rows: list[dict[str, Any]]) -> str:
    """Return a markdown table of ACT iterations, including a **Σ** totals row."""
    if not act_rows:
        return ""

    lines = [_HEADER, _SEP]
    total_calls = 0
    total_errors = 0
    total_ms = 0.0

    for row in act_rows:
        cycle = row["cycle"]
        calls = row["tool_call_count"]
        errors = row["tool_error_count"]
        ms = row["tool_total_ms"]
        reason = row["finish_reason"]
        completed = "Y" if row["completed"] else "N"
        lines.append(f"| {cycle} | {calls} | {errors} | {ms} | {reason} | {completed} |")
        total_calls += calls
        total_errors += errors
        total_ms += ms

    lines.append(f"| **\u03a3** | {total_calls} | {total_errors} | {total_ms} | \u2014 | \u2014 |")
    return "\n".join(lines) + "\n"


def format_soak_summary(
    mind_dir: Path | str,
    run_id: str,
    spend_usd: float | None = None,
) -> str:
    """Read a soak run's ACT-tools ledger and return a full summary.

    When ``spend_usd`` is given (the run-cumulative cost, read by the CLI
    from the run DB), it is appended to the headline. It is a parameter,
    not a file read, because cost is not in the ledger (it lives in the
    run's SQLite ``api_calls``) \u2014 keeping this function file-only-testable.
    """
    path = Path(mind_dir) / "soak" / run_id / "act-tools.jsonl"
    rows = _read_jsonl(path)
    if not rows:
        return "# Soak " + run_id + " \u2014 no ACT records\n"
    headline = "# Soak " + run_id + " \u2014 " + str(len(rows)) + " ACT cycles"
    if spend_usd is not None:
        headline += f", ${spend_usd:.2f} spent"
    return headline + "\n" + format_iteration_table(rows)


def run_spend_from_db(state_dir: Path | str) -> float | None:
    """Best-effort run-cumulative spend (USD) from a soak run's DB, or None.

    Reads ``<state_dir>/chimera.db`` and sums token-priced ``api_calls``
    via :func:`chimera.core.budget.rolling_spend_usd` over an effectively
    unbounded window (a soak DB is per-run, so the total IS the run spend).
    Fail-soft: any error (missing DB, locked, pricing gap) returns ``None``
    so the CLI simply omits the spend figure. Primarily meaningful when run
    from a soak worktree (where the DB holds that run's calls); on a pruned
    or unrelated DB it returns None or an irrelevant total, hence best-effort.
    """
    try:
        from chimera.core.budget import rolling_spend_usd
        from chimera.memory.store import connect

        db_path = Path(state_dir) / "chimera.db"
        if not db_path.exists():
            return None
        conn = connect(db_path)
        try:
            return rolling_spend_usd(conn, minutes=100 * 365 * 24 * 60)
        finally:
            conn.close()
    except Exception:
        return None