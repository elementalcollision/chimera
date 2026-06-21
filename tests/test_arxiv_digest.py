"""Recurring arXiv feed ingestion → ranked digest (ADR 0186)."""

from __future__ import annotations

import json

from chimera.core.arxiv_digest import (
    load_chimera_feed,
    rank_records,
    render_digest,
    score_record,
    write_digest_if_new,
)


def _rec(arxiv_id, primary, work_items, *, links=None, title="A paper", pub="2026-06-21"):
    return {
        "arxiv_id": arxiv_id, "abs_url": f"http://arxiv.org/abs/{arxiv_id}",
        "title": title, "abstract": "abstract", "primary_category": primary,
        "categories": [primary], "work_items": work_items, "links": links or {},
        "published": pub,
    }


# ── scoring ─────────────────────────────────────────────────────────


def test_score_rewards_code_core_cat_and_substantive_work():
    strong = _rec("1", "cs.SE", ["algorithm"], links={"github": ["http://g/x"]},
                  title="Multi-agent code repository agent")
    weak = _rec("2", "cs.LG", ["benchmark"], title="A dataset")
    assert score_record(strong) > score_record(weak)


def test_benchmark_only_is_penalized():
    # benchmark-only loses a point vs a substantive work item, all else equal.
    bench = _rec("1", "cs.AI", ["benchmark"], title="x")
    algo = _rec("2", "cs.AI", ["algorithm"], title="x")
    assert score_record(algo) > score_record(bench)


def test_rank_orders_best_first():
    recs = [
        _rec("low", "cs.LG", ["benchmark"], title="dataset"),
        _rec("hi", "cs.SE", ["algorithm"], links={"github": ["u"]},
             title="agent code repository tool-use"),
    ]
    assert [r["arxiv_id"] for r in rank_records(recs)][0] == "hi"


# ── render ──────────────────────────────────────────────────────────


def test_render_has_shortlist_and_tail():
    recs = [_rec(str(i), "cs.AI", ["algorithm"], title=f"P{i}") for i in range(5)]
    md = render_digest(recs, "2026-06-21", top_n=2)
    assert "# arXiv Chimera digest — 2026-06-21" in md
    assert "## Shortlist" in md and "## Also matched (tail)" in md
    assert "Feed records (post scraper-filter): 5" in md


# ── load + write (fail-soft, idempotent) ────────────────────────────


def _write_feed(tmp_path, records, run_date="2026-06-21"):
    p = tmp_path / "chimera.json"
    p.write_text(json.dumps({"run_date": run_date, "records": records}))
    return p


def test_load_feed_failsoft_on_missing():
    assert load_chimera_feed("/no/such/feed.json") == ("", [])


def test_write_digest_if_new_writes_then_skips(tmp_path):
    feed = _write_feed(tmp_path, [_rec("1", "cs.SE", ["algorithm"])])
    out = tmp_path / "research"
    s1 = write_digest_if_new(feed, out)
    assert s1["status"] == "written" and s1["run_date"] == "2026-06-21"
    assert (out / "arxiv-digest-2026-06-21.md").exists()
    # Idempotent: re-run for the same feed run does NOT rewrite.
    s2 = write_digest_if_new(feed, out)
    assert s2["status"] == "exists"


def test_write_digest_if_new_failsoft_on_no_feed(tmp_path):
    s = write_digest_if_new(tmp_path / "missing.json", tmp_path / "research")
    assert s["status"] == "no-feed" and s["path"] is None
