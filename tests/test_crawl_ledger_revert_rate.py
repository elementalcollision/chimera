"""crawl_ledger.revert_rate — fraction of folded outcomes reverted (spec 10).

Mirrors spec 06 (merge_rate). Dogfoods B.4k: spec acceptance cases + a seeded
fuzz_oracle.fuzz_check property test for the invariant.
"""

from __future__ import annotations

from chimera.core.crawl_ledger import (
    CrawlOutcome,
    _disposition_rate,
    record_outcome,
    revert_rate,
    set_disposition,
)
from chimera.core.fuzz_oracle import fuzz_check


def _record(state, run_id, disposition, ts="2026-06-15T00:00:00+00:00"):
    record_outcome(state, CrawlOutcome(run_id=run_id, ts=ts, slug="s", gate="pass"))
    if disposition != "pending":
        set_disposition(state, run_id, disposition)


# ── spec acceptance cases ───────────────────────────────────────────


def test_one_reverted_one_merged_is_half(tmp_path):
    _record(tmp_path, "r1", "reverted")
    _record(tmp_path, "r2", "merged")
    assert revert_rate(tmp_path) == 0.5


def test_no_outcomes_is_zero(tmp_path):
    assert revert_rate(tmp_path) == 0.0


def test_since_after_all_is_zero(tmp_path):
    _record(tmp_path, "r1", "reverted", ts="2026-06-15T00:00:00+00:00")
    assert revert_rate(tmp_path, since="2026-06-20T00:00:00+00:00") == 0.0


# ── B.4k property-fuzz: rate ∈ [0,1] and == reverted/total over the window ──

_DISPS = ("pending", "merged", "reverted", "abandoned")


def _gen(rng):
    n = rng.randint(0, 8)
    return [
        CrawlOutcome(run_id=f"r{i}", ts=f"2026-06-{10 + rng.randint(0, 9):02d}",
                     slug="s", gate="pass", disposition=rng.choice(_DISPS))
        for i in range(n)
    ]


def _reverted_invariant(outcomes, out):
    total = len(outcomes)
    expected = (round(sum(1 for o in outcomes if o.disposition == "reverted") / total, 4)
                if total else 0.0)
    return 0.0 <= out <= 1.0 and out == expected


def test_revert_rate_property_fuzz():
    res = fuzz_check(lambda outs: _disposition_rate(outs, "reverted"),
                     _gen, _reverted_invariant, trials=400, seed=2)
    assert res.ok, res
