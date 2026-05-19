"""History formatter — recent api_call summary for the system prompt.

Per pillar-adaptability.md Pattern 2 (autoresearch ``format_history_for_prompt``).
Shows the model what it has been doing recently so subsequent decisions
can build on past outcomes without re-deriving.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryStats:
    cycles_covered: int
    total_calls: int
    by_finish: dict[str, int]
    by_model: dict[str, int]
    last_n_lines: list[str]

    def render(self) -> str:
        if self.total_calls == 0:
            return "history: (none yet — this looks like a fresh session)"
        finishes = ", ".join(f"{k}={v}" for k, v in sorted(self.by_finish.items()))
        models = ", ".join(f"{k}={v}" for k, v in sorted(self.by_model.items()))
        lines = ["history (last few api calls):"]
        lines.append(f"  calls={self.total_calls}, by_finish=[{finishes}], by_model=[{models}]")
        for line in self.last_n_lines:
            lines.append(f"  - {line}")
        return "\n".join(lines)


def recent_history(
    conn: sqlite3.Connection,
    *,
    current_cycle: int,
    last_n_cycles: int = 3,
    tail_calls: int = 5,
) -> HistoryStats:
    cutoff = max(0, current_cycle - last_n_cycles)
    rows = conn.execute(
        "SELECT cycle, provider, model_id, finish_reason, output_tokens, latency_ms "
        "FROM api_calls WHERE cycle >= ? AND cycle < ? ORDER BY id",
        (cutoff, current_cycle),
    ).fetchall()
    by_finish: dict[str, int] = {}
    by_model: dict[str, int] = {}
    for r in rows:
        by_finish[r["finish_reason"] or "?"] = by_finish.get(r["finish_reason"] or "?", 0) + 1
        by_model[r["model_id"]] = by_model.get(r["model_id"], 0) + 1
    tail = rows[-tail_calls:] if rows else []
    lines = [
        f"cycle {r['cycle']}: {r['model_id']} → {r['finish_reason']} "
        f"({r['output_tokens'] or '?'} out, {r['latency_ms'] or '?'}ms)"
        for r in tail
    ]
    return HistoryStats(
        cycles_covered=last_n_cycles,
        total_calls=len(rows),
        by_finish=by_finish,
        by_model=by_model,
        last_n_lines=lines,
    )
