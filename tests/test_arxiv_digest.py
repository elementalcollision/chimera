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


def test_write_digest_if_new_failsoft_on_no_feed(tmp_path):
    s = write_digest_if_new(tmp_path / "missing.json", tmp_path / "research")
    assert s["status"] == "no-feed" and s["path"] is None


# ── delta-dedup (seen ledger) ───────────────────────────────────────


def test_delta_dedup_first_run_writes_then_no_new(tmp_path):
    feed = _write_feed(tmp_path, [_rec("1", "cs.SE", ["algorithm"]),
                                  _rec("2", "cs.AI", ["proof"])])
    out, seen = tmp_path / "research", tmp_path / "seen.json"
    s1 = write_digest_if_new(feed, out, seen_path=seen)
    assert s1["status"] == "written" and s1["count"] == 2 and s1["total"] == 2
    assert (out / "arxiv-digest-2026-06-21.md").exists()
    # Re-running the SAME overlapping feed now surfaces nothing new.
    s2 = write_digest_if_new(feed, out, seen_path=seen)
    assert s2["status"] == "no-new" and s2["count"] == 0 and s2["total"] == 2


def test_delta_dedup_surfaces_only_fresh(tmp_path):
    out, seen = tmp_path / "research", tmp_path / "seen.json"
    write_digest_if_new(_write_feed(tmp_path, [_rec("1", "cs.SE", ["algorithm"])]),
                        out, seen_path=seen)
    # Next run: id 1 (seen) + id 2 (new) → only id 2 is fresh.
    feed2 = _write_feed(tmp_path, [_rec("1", "cs.SE", ["algorithm"]),
                                   _rec("2", "cs.AI", ["proof"])], run_date="2026-06-22")
    s = write_digest_if_new(feed2, out, seen_path=seen)
    assert s["status"] == "written" and s["count"] == 1 and s["total"] == 2
    body = (out / "arxiv-digest-2026-06-22.md").read_text()
    assert "arXiv:2" in body and "arXiv:1" not in body


def test_version_suffix_deduped(tmp_path):
    # v1 then v2 of the same paper is the SAME work → not re-surfaced.
    out, seen = tmp_path / "research", tmp_path / "seen.json"
    write_digest_if_new(_write_feed(tmp_path, [_rec("2606.1v1", "cs.SE", ["algorithm"])]),
                        out, seen_path=seen)
    s = write_digest_if_new(
        _write_feed(tmp_path, [_rec("2606.1v2", "cs.SE", ["algorithm"])], run_date="2026-06-22"),
        out, seen_path=seen)
    assert s["status"] == "no-new"


def test_seen_ledger_roundtrip_and_failsoft(tmp_path):
    from chimera.core.arxiv_digest import load_seen, save_seen
    assert load_seen(tmp_path / "absent.json") == set()
    save_seen(tmp_path / "s.json", {"b", "a"})
    assert load_seen(tmp_path / "s.json") == {"a", "b"}


def test_without_seen_path_writes_full_no_dedup(tmp_path):
    # Back-compat: no seen_path → writes the full feed (no dedup).
    feed = _write_feed(tmp_path, [_rec("1", "cs.SE", ["algorithm"])])
    s = write_digest_if_new(feed, tmp_path / "research")
    assert s["status"] == "written" and s["count"] == 1
