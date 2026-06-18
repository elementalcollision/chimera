"""Deterministic token/cost-delta analyzer for soak A/Bs (ADR 0183 + flag graduation).

Key-free: reads two ``api_calls`` SQLite DBs — a *baseline* and a *treatment*
(e.g. a flag OFF vs ON soak, or model A vs B) — and emits the token/cost-delta
verdict that the COMPLEXITY_ROUTING / TOOL_PREFILTER graduations (and code-model
A/Bs) need. Cost is **derived from tokens × the in-code price table** (the same
basis as ``chimera cost``), so the verdict is fully reproducible offline with no
API access. Turns the eventual keyed soak into a one-command verdict.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .budget import _price_table

#: |cost Δ%| below this is reported as "negligible" rather than a win/loss.
_NEGLIGIBLE_PCT = 2.0


@dataclass(frozen=True)
class DbCosts:
    """Aggregated cost of the successful api_calls in one DB."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def read_db_costs(db_path: str | Path) -> DbCosts:
    """Aggregate successful ``api_calls`` in ``db_path``. Cost is derived from
    tokens × the in-code price table (consistent with ``chimera cost``); rows
    with a non-NULL ``error`` are excluded, and unknown models price at $0."""
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT model_id, "
            "  COUNT(*) AS n, "
            "  COALESCE(SUM(input_tokens), 0) AS in_tok, "
            "  COALESCE(SUM(output_tokens), 0) AS out_tok "
            "FROM api_calls WHERE error IS NULL GROUP BY model_id"
        ).fetchall()
    finally:
        con.close()

    table = _price_table()
    calls = in_tok = out_tok = 0
    cost = 0.0
    for r in rows:
        ip, op = table.get(r["model_id"], (0.0, 0.0))
        calls += r["n"]
        in_tok += r["in_tok"]
        out_tok += r["out_tok"]
        cost += (r["in_tok"] / 1_000_000.0) * ip + (r["out_tok"] / 1_000_000.0) * op
    return DbCosts(calls=calls, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)


def _pct(base: float, treat: float) -> float:
    """Signed percent change base→treat; 0.0 when base is 0 (avoids div-by-zero)."""
    if base == 0:
        return 0.0
    return round((treat - base) / base * 100.0, 2)


@dataclass(frozen=True)
class CostDelta:
    """The treatment-vs-baseline delta (treatment − baseline)."""

    baseline: DbCosts
    treatment: DbCosts

    @property
    def token_delta(self) -> int:
        return self.treatment.total_tokens - self.baseline.total_tokens

    @property
    def cost_delta(self) -> float:
        return round(self.treatment.cost_usd - self.baseline.cost_usd, 6)

    @property
    def token_pct(self) -> float:
        return _pct(self.baseline.total_tokens, self.treatment.total_tokens)

    @property
    def cost_pct(self) -> float:
        return _pct(self.baseline.cost_usd, self.treatment.cost_usd)

    def verdict(self) -> str:
        """Cost-only verdict (quality is judged separately by the soak's gate)."""
        p = self.cost_pct
        if abs(p) < _NEGLIGIBLE_PCT:
            return f"negligible cost change ({p:+.2f}%)"
        if p < 0:
            return f"treatment CHEAPER by {abs(p):.2f}% (${abs(self.cost_delta):.4f})"
        return f"treatment COSTLIER by {p:.2f}% (${self.cost_delta:.4f})"

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "treatment": self.treatment.to_dict(),
            "token_delta": self.token_delta,
            "token_pct": self.token_pct,
            "cost_delta": self.cost_delta,
            "cost_pct": self.cost_pct,
            "verdict": self.verdict(),
        }


def compute_cost_delta(baseline_db: str | Path, treatment_db: str | Path) -> CostDelta:
    """Read both DBs and return the treatment-vs-baseline :class:`CostDelta`."""
    return CostDelta(read_db_costs(baseline_db), read_db_costs(treatment_db))
