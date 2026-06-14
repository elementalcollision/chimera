"""CRAWL outcome ledger — since-filtering tests for summarize_outcomes (ADR 0182)."""

from __future__ import annotations

from chimera.core.crawl_ledger import (
    CrawlOutcome,
    record_outcome,
    set_disposition,
    summarize_outcomes,
)


def _outcome(run_id, ts="2026-06-13T10:00:00+00:00", gate="pass", cost=0.1, slug="s", **kw):
    return CrawlOutcome(run_id=run_id, ts=ts,
                        slug=slug, gate=gate, cost_usd=cost, **kw)


def test_since_filters_older_outcomes(tmp_path):
    record_outcome(tmp_path, _outcome("r1", ts="2026-06-10T00:00:00+00:00", gate="pass", cost=0.5))
    record_outcome(tmp_path, _outcome("r2", ts="2026-06-20T00:00:00+00:00", gate="pass", cost=0.3))
    set_disposition(tmp_path, "r1", "merged")
    set_disposition(tmp_path, "r2", "merged")

    s = summarize_outcomes(tmp_path, since="2026-06-15T00:00:00+00:00")
    assert s["total"] == 1  # only r2
    assert s["merged"] == 1
    assert s["total_cost_usd"] == 0.3


def test_since_none_includes_all(tmp_path):
    record_outcome(tmp_path, _outcome("r1", ts="2026-06-10T00:00:00+00:00", gate="pass"))
    record_outcome(tmp_path, _outcome("r2", ts="2026-06-20T00:00:00+00:00", gate="fail"))

    s_default = summarize_outcomes(tmp_path)
    s_explicit = summarize_outcomes(tmp_path, since=None)
    assert s_default["total"] == 2
    assert s_explicit["total"] == 2


def test_since_excludes_all_when_none_after(tmp_path):
    record_outcome(tmp_path, _outcome("r1", ts="2026-06-10T00:00:00+00:00", gate="pass"))
    record_outcome(tmp_path, _outcome("r2", ts="2026-06-11T00:00:00+00:00", gate="fail"))

    s = summarize_outcomes(tmp_path, since="2026-06-12T00:00:00+00:00")
    assert s == {"total": 0}


def test_since_edge_inclusive(tmp_path):
    record_outcome(tmp_path, _outcome("r1", ts="2026-06-13T10:00:00+00:00", gate="pass"))
    s = summarize_outcomes(tmp_path, since="2026-06-13T10:00:00+00:00")
    assert s["total"] == 1  # >= is inclusive


def test_since_with_disposition_mix(tmp_path):
    record_outcome(tmp_path, _outcome("r1", ts="2026-01-01T00:00:00+00:00", gate="pass", cost=1.0))
    record_outcome(tmp_path, _outcome("r2", ts="2026-03-01T00:00:00+00:00", gate="pass", cost=2.0))
    record_outcome(tmp_path, _outcome("r3", ts="2026-05-01T00:00:00+00:00", gate="fail", cost=3.0))
    set_disposition(tmp_path, "r2", "merged")
    set_disposition(tmp_path, "r3", "reverted")

    s = summarize_outcomes(tmp_path, since="2026-03-01T00:00:00+00:00")
    assert s["total"] == 2
    assert s["gate_pass"] == 1
    assert s["merged"] == 1
    assert s["reverted"] == 1
