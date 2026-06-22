"""HealthSummary.from_dict — inverse of to_dict, round-trippable (spec 09).

Dogfoods B.4k: the round-trip is the textbook property — a seeded
fuzz_oracle.fuzz_check pins `from_dict(to_dict(s)) == s` for arbitrary summaries.
"""

from __future__ import annotations

from chimera.core.fuzz_oracle import fuzz_check
from chimera.core.health import HealthDimension, HealthSummary


def test_multi_dimension_roundtrip():
    s = HealthSummary(overall="red", dimensions=[
        HealthDimension(key="cost", label="Cost", status="red", detail="over budget"),
        HealthDimension(key="drift", label="Drift", status="amber", detail="rising"),
    ])
    assert HealthSummary.from_dict(s.to_dict()) == s


def test_empty_summary_roundtrip():
    s = HealthSummary(overall="green", dimensions=[])
    assert HealthSummary.from_dict(s.to_dict()) == s


# ── B.4k property-fuzz: round-trip for any summary ──────────────────

_STATUSES = ("green", "amber", "red", "unknown")


def _gen_summary(rng):
    n = rng.randint(0, 5)
    dims = [HealthDimension(key=f"k{i}", label=f"L{i}", status=rng.choice(_STATUSES),
                            detail=f"d{i}") for i in range(n)]
    return HealthSummary(overall=rng.choice(_STATUSES), dimensions=dims)


def test_from_dict_roundtrip_property_fuzz():
    res = fuzz_check(lambda s: HealthSummary.from_dict(s.to_dict()),
                     _gen_summary, lambda s, out: out == s, trials=400, seed=0)
    assert res.ok, res
