"""Deterministic cost/token-delta analyzer (chimera.core.cost_delta).

Builds synthetic api_calls DBs and asserts the token/cost deltas + verdict.
Key-free and offline — cost derives from tokens × the in-code price table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from chimera.core.cost_delta import (
    DbCosts,
    compute_cost_delta,
    read_db_costs,
)
from chimera.providers.tiers import LADDER_QWEN37_MAX

MODEL = LADDER_QWEN37_MAX.model_id  # qwen/qwen3.7-max — in the price table
IN_P = LADDER_QWEN37_MAX.input_cost_per_mtok
OUT_P = LADDER_QWEN37_MAX.output_cost_per_mtok


def _mkdb(path: Path, rows: list[tuple[str, int, int, str | None]]) -> None:
    """rows: (model_id, input_tokens, output_tokens, error)."""
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE api_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "cycle INTEGER NOT NULL, provider TEXT NOT NULL, model_id TEXT NOT NULL, "
        "input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, "
        "error TEXT, created_at TEXT NOT NULL)"
    )
    con.executemany(
        "INSERT INTO api_calls (cycle, provider, model_id, input_tokens, "
        "output_tokens, error, created_at) VALUES (0, 'openrouter', ?, ?, ?, ?, 't')",
        rows,
    )
    con.commit()
    con.close()


def _cost(in_tok: int, out_tok: int) -> float:
    return (in_tok / 1_000_000.0) * IN_P + (out_tok / 1_000_000.0) * OUT_P


def test_read_db_costs_derives_from_tokens_and_excludes_errors(tmp_path):
    db = tmp_path / "a.db"
    _mkdb(db, [
        (MODEL, 1_000_000, 1_000_000, None),
        (MODEL, 500_000, 0, None),
        (MODEL, 9_999_999, 9_999_999, "boom"),  # error row — excluded
    ])
    c = read_db_costs(db)
    assert isinstance(c, DbCosts)
    assert c.calls == 2
    assert c.input_tokens == 1_500_000
    assert c.output_tokens == 1_000_000
    assert abs(c.cost_usd - _cost(1_500_000, 1_000_000)) < 1e-9


def test_treatment_cheaper_verdict(tmp_path):
    base = tmp_path / "base.db"
    treat = tmp_path / "treat.db"
    _mkdb(base, [(MODEL, 1_000_000, 1_000_000, None)])
    _mkdb(treat, [(MODEL, 500_000, 500_000, None)])
    d = compute_cost_delta(base, treat)
    assert d.token_delta == -1_000_000
    assert d.token_pct == -50.0
    assert d.cost_pct == -50.0
    assert "CHEAPER" in d.verdict()
    assert d.to_dict()["cost_delta"] < 0


def test_treatment_costlier_verdict(tmp_path):
    base = tmp_path / "b.db"
    treat = tmp_path / "t.db"
    _mkdb(base, [(MODEL, 1_000_000, 0, None)])
    _mkdb(treat, [(MODEL, 2_000_000, 0, None)])
    d = compute_cost_delta(base, treat)
    assert d.cost_pct == 100.0
    assert "COSTLIER" in d.verdict()


def test_negligible_change_verdict(tmp_path):
    base = tmp_path / "b.db"
    treat = tmp_path / "t.db"
    _mkdb(base, [(MODEL, 1_000_000, 0, None)])
    _mkdb(treat, [(MODEL, 1_005_000, 0, None)])  # +0.5%
    d = compute_cost_delta(base, treat)
    assert "negligible" in d.verdict()


def test_empty_dbs_are_zero_safe(tmp_path):
    base = tmp_path / "b.db"
    treat = tmp_path / "t.db"
    _mkdb(base, [])
    _mkdb(treat, [])
    d = compute_cost_delta(base, treat)
    assert d.token_delta == 0 and d.cost_delta == 0.0
    assert d.cost_pct == 0.0  # no div-by-zero
    assert "negligible" in d.verdict()


def test_unknown_model_prices_at_zero(tmp_path):
    db = tmp_path / "u.db"
    _mkdb(db, [("made-up/model-x", 1_000_000, 1_000_000, None)])
    c = read_db_costs(db)
    assert c.input_tokens == 1_000_000  # tokens still counted
    assert c.cost_usd == 0.0            # unknown model → $0, no crash
