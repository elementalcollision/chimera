"""Seeded-fuzz correctness oracle (ADR 0186 B.4k)."""

from __future__ import annotations

import math

from chimera.core.fuzz_oracle import FuzzResult, differential_check, fuzz_check

# A deterministic integer generator (seeded → reproducible sequence).
def _ints(lo=-100, hi=100):
    return lambda rng: rng.randint(lo, hi)


# ── fuzz_check: property mode ────────────────────────────────────────


def test_fuzz_check_passes_when_property_always_holds():
    # abs(x) is always >= 0.
    res = fuzz_check(abs, _ints(), lambda inp, out: out >= 0, trials=200, seed=1)
    assert res.ok and res.trials == 200 and res.passed == 200
    assert res.counterexample is None and res.detail is None
    assert isinstance(res, FuzzResult)


def test_fuzz_check_finds_property_counterexample():
    # Buggy "square": wrong (returns x) for negatives → property out == x*x breaks.
    buggy = lambda x: x * x if x >= 0 else x
    res = fuzz_check(buggy, _ints(), lambda inp, out: out == inp * inp,
                     trials=200, seed=1)
    assert res.ok is False
    assert res.counterexample is not None and res.counterexample < 0
    assert res.detail == "property returned False"
    assert res.passed == res.trials - 1  # failed on the trial it stopped at


def test_fuzz_check_candidate_exception_is_counterexample():
    # Crashes on 0 (ZeroDivisionError) → that input is the counterexample.
    res = fuzz_check(lambda x: 1 / x, _ints(-3, 3), lambda inp, out: True,
                     trials=300, seed=7)
    assert res.ok is False and res.counterexample == 0
    assert "ZeroDivisionError" in (res.detail or "")


def test_fuzz_check_property_exception_is_counterexample():
    def boom(inp, out):
        raise ValueError("cannot verify")
    res = fuzz_check(abs, _ints(), boom, trials=10, seed=0)
    assert res.ok is False and "ValueError: cannot verify" in (res.detail or "")


def test_fuzz_check_is_deterministic_for_a_seed():
    buggy = lambda x: x * x if x >= 0 else x
    prop = lambda inp, out: out == inp * inp
    a = fuzz_check(buggy, _ints(), prop, trials=200, seed=42)
    b = fuzz_check(buggy, _ints(), prop, trials=200, seed=42)
    assert not a.ok and not b.ok
    assert a.counterexample == b.counterexample and a.trials == b.trials
    assert a.seed == 42


def test_fuzz_check_records_round_trip_property():
    # encode/decode round-trip: str(int) -> int is identity.
    res = fuzz_check(lambda x: int(str(x)), _ints(-10**9, 10**9),
                     lambda inp, out: out == inp, trials=100, seed=3)
    assert res.ok and res.passed == 100


# ── differential_check: old-code-as-reference mode ───────────────────


def test_differential_passes_for_equivalent_impls():
    baseline = lambda x: x * 2
    candidate = lambda x: x + x
    res = differential_check(baseline, candidate, _ints(), trials=200, seed=1)
    assert res.ok and res.passed == 200 and res.counterexample is None


def test_differential_finds_divergence():
    baseline = lambda x: x * 2
    candidate = lambda x: x * 2 if x != 5 else 999  # diverges at 5
    res = differential_check(baseline, candidate, _ints(0, 10), trials=500, seed=2)
    assert res.ok is False and res.counterexample == 5
    assert "baseline=10" in (res.detail or "") and "candidate=999" in (res.detail or "")


def test_differential_same_exception_type_is_preserved_behaviour():
    # Both raise ZeroDivisionError on 0 → behaviour preserved (not a divergence).
    res = differential_check(lambda x: 1 / x, lambda x: 2 / x, _ints(-2, 2),
                             trials=300, seed=4)
    # candidate (2/x) != baseline (1/x) on nonzero inputs → it WILL diverge there,
    # but the point: a shared 0 raising the same type is not what fails it.
    assert res.ok is False  # diverges on nonzero values
    # craft a case where they only ever hit 0:
    res0 = differential_check(lambda x: 1 / x, lambda x: 5 / x, lambda rng: 0,
                              trials=10, seed=0)
    assert res0.ok is True  # both raise ZeroDivisionError every time


def test_differential_one_raises_other_returns_is_divergence():
    # Agree on every nonzero input (both 1/x); differ only at 0, where the baseline
    # returns and the candidate raises → the sole counterexample is 0.
    baseline = lambda x: 0.0 if x == 0 else 1 / x   # handles 0, never raises
    candidate = lambda x: 1 / x                       # raises on 0
    res = differential_check(baseline, candidate, _ints(-2, 2), trials=300, seed=11)
    assert res.ok is False and res.counterexample == 0
    assert "raised ZeroDivisionError" in (res.detail or "")


def test_differential_custom_equal_for_floats():
    baseline = lambda x: x / 3.0
    candidate = lambda x: x * (1.0 / 3.0)  # tiny float error
    strict = differential_check(baseline, candidate, _ints(1, 50), trials=200, seed=5)
    close = differential_check(baseline, candidate, _ints(1, 50), trials=200, seed=5,
                               equal=lambda a, b: math.isclose(a, b, rel_tol=1e-9))
    # strict == may or may not diverge depending on values; isclose must always hold.
    assert close.ok is True
    assert strict.seed == 5 and close.seed == 5
