"""crawl_ledger.outcomes_for_slug — folded outcomes for one spec (spec 07)."""

from __future__ import annotations

from chimera.core.crawl_ledger import CrawlOutcome, outcomes_for_slug, record_outcome


def test_returns_matching_slug_in_first_seen_order(tmp_path):
    record_outcome(tmp_path, CrawlOutcome(run_id="r1", ts="t1", slug="a", gate="pass"))
    record_outcome(tmp_path, CrawlOutcome(run_id="r2", ts="t2", slug="b", gate="pass"))
    record_outcome(tmp_path, CrawlOutcome(run_id="r3", ts="t3", slug="a", gate="fail"))
    got = outcomes_for_slug(tmp_path, "a")
    assert [o.run_id for o in got] == ["r1", "r3"]
    assert all(o.slug == "a" for o in got)


def test_unknown_slug_is_empty(tmp_path):
    record_outcome(tmp_path, CrawlOutcome(run_id="r1", ts="t1", slug="a", gate="pass"))
    assert outcomes_for_slug(tmp_path, "zzz") == []
