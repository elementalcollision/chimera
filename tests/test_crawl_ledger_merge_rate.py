"""crawl_ledger.merge_rate — fraction of folded outcomes merged (spec 06).

Dogfoods B.4k: alongside the spec's fixed-input acceptance cases, a seeded
fuzz_oracle.fuzz_check property test (the kind a spec `property:` field asks the agent
to write) pins the invariant across the whole input space, not just three examples.
"""

from __future__ import annotations

from chimera.core.crawl_ledger import (
    CrawlOutcome,
    _disposition_rate,
    merge_rate,
    record_outcome,
    set_disposition,
)
from chimera.core.fuzz_oracle import fuzz_check


def _record(state, run_id, disposition, ts="2026-06-15T00:00:00+00:00"):
    record_outcome(state, CrawlOutcome(run_id=run_id, ts=ts, slug="s", gate="pass"))
    if disposition != "pending":
        set_disposition(state, run_id, disposition)


# ── spec acceptance cases ───────────────────────────────────────────


def test_one_merged_one_abandoned_is_half(tmp_path):
    _record(tmp_path, "r1", "merged")
    _record(tmp_path, "r2", "abandoned")
    assert merge_rate(tmp_path) == 0.5


def test_no_outcomes_is_zero(tmp_path):
    assert merge_rate(tmp_path) == 0.0


def test_since_after_all_is_zero(tmp_path):
    _record(tmp_path, "r1", "merged", ts="2026-06-15T00:00:00+00:00")
    assert merge_rate(tmp_path, since="2026-06-20T00:00:00+00:00") == 0.0


# ── B.4k property-fuzz: rate ∈ [0,1] and == merged/total over the window ──

_DISPS = ("pending", "merged", "reverted", "abandoned")


def _gen(rng):
    n = rng.randint(0, 8)
    return [
        CrawlOutcome(run_id=f"r{i}", ts=f"2026-06-{10 + rng.randint(0, 9):02d}",
                     slug="s", gate="pass", disposition=rng.choice(_DISPS))
        for i in range(n)
    ]


def _merged_invariant(outcomes, out):
    total = len(outcomes)
    expected = (round(sum(1 for o in outcomes if o.disposition == "merged") / total, 4)
                if total else 0.0)
    return 0.0 <= out <= 1.0 and out == expected


def test_merge_rate_property_fuzz():
    res = fuzz_check(lambda outs: _disposition_rate(outs, "merged"),
                     _gen, _merged_invariant, trials=400, seed=0)
    assert res.ok, res


def test_merge_rate_property_fuzz_with_since():
    def gen_with_since(rng):
        return (_gen(rng), f"2026-06-{10 + rng.randint(0, 9):02d}")

    def prop(pair, out):
        outs, since = pair
        win = [o for o in outs if o.ts >= since]
        total = len(win)
        expected = (round(sum(1 for o in win if o.disposition == "merged") / total, 4)
                    if total else 0.0)
        return 0.0 <= out <= 1.0 and out == expected

    res = fuzz_check(lambda pair: _disposition_rate(pair[0], "merged", pair[1]),
                     gen_with_since, prop, trials=400, seed=1)
    assert res.ok, res
