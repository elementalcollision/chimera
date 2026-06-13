"""CRAWL outcome ledger — RUN-graduation evidence base (ADR 0182 Phase 3)."""

from __future__ import annotations


from chimera.core.crawl_ledger import (
    CrawlOutcome,
    read_outcomes,
    record_outcome,
    set_disposition,
    summarize_outcomes,
)


def _outcome(run_id, gate="pass", cost=0.1, slug="s", **kw):
    return CrawlOutcome(run_id=run_id, ts="2026-06-13T10:00:00+00:00",
                        slug=slug, gate=gate, cost_usd=cost, **kw)


def test_record_and_read_roundtrip(tmp_path):
    record_outcome(tmp_path, _outcome("r1", committed=1, branch="b1"))
    got = read_outcomes(tmp_path)
    assert len(got) == 1
    assert got[0].run_id == "r1"
    assert got[0].committed == 1
    assert got[0].disposition == "pending"


def test_empty_ledger(tmp_path):
    assert read_outcomes(tmp_path) == []
    assert summarize_outcomes(tmp_path) == {"total": 0}


def test_latest_per_run_id_wins(tmp_path):
    record_outcome(tmp_path, _outcome("r1", gate="fail"))
    record_outcome(tmp_path, _outcome("r1", gate="pass"))  # re-append (update)
    got = read_outcomes(tmp_path)
    assert len(got) == 1            # folded by run_id
    assert got[0].gate == "pass"    # latest wins


def test_set_disposition_appends_update(tmp_path):
    record_outcome(tmp_path, _outcome("r1"))
    assert set_disposition(tmp_path, "r1", "merged") is True
    assert read_outcomes(tmp_path)[0].disposition == "merged"


def test_set_disposition_unknown_run_or_status(tmp_path):
    record_outcome(tmp_path, _outcome("r1"))
    assert set_disposition(tmp_path, "nope", "merged") is False
    assert set_disposition(tmp_path, "r1", "bogus") is False


def test_summarize_metrics(tmp_path):
    record_outcome(tmp_path, _outcome("r1", gate="pass", cost=0.20))
    record_outcome(tmp_path, _outcome("r2", gate="pass", cost=0.10))
    record_outcome(tmp_path, _outcome("r3", gate="fail", cost=0.05))
    set_disposition(tmp_path, "r1", "merged")
    set_disposition(tmp_path, "r2", "reverted")

    s = summarize_outcomes(tmp_path)
    assert s["total"] == 3
    assert s["gate_pass"] == 2
    assert s["gate_pass_rate"] == round(2 / 3, 4)
    assert s["merged"] == 1
    assert s["reverted"] == 1
    assert s["revert_rate"] == 1.0          # 1 reverted / 1 merged
    assert s["by_disposition"]["merged"] == 1
    assert s["by_disposition"]["reverted"] == 1
    assert s["by_disposition"]["pending"] == 1
    assert s["total_cost_usd"] == 0.35
    assert s["cost_per_landed_usd"] == 0.35  # total / 1 merged


def test_revert_and_landed_none_when_no_merges(tmp_path):
    record_outcome(tmp_path, _outcome("r1", gate="pass"))
    s = summarize_outcomes(tmp_path)
    assert s["revert_rate"] is None
    assert s["cost_per_landed_usd"] is None


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "crawl" / "outcomes.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text('not json\n{"run_id": "r1", "gate": "pass"}\n{"no_run_id": 1}\n')
    got = read_outcomes(tmp_path)
    assert [o.run_id for o in got] == ["r1"]
