"""Seeded-fuzz correctness oracle (ADR 0186 B.4k)."""

from __future__ import annotations

import math
from random import Random

import pytest

from chimera.core.fuzz_oracle import (
    FuzzResult,
    differential_check,
    fuzz_check,
    gen_bool,
    gen_choice,
    gen_float,
    gen_int,
    gen_list,
    gen_one_of,
    gen_text,
    gen_tuple,
)


# A deterministic integer generator (seeded → reproducible sequence).
def _ints(lo=-100, hi=100):
    def gen(rng):
        return rng.randint(lo, hi)
    return gen


# ── fuzz_check: property mode ────────────────────────────────────────


def test_fuzz_check_passes_when_property_always_holds():
    # abs(x) is always >= 0.
    res = fuzz_check(abs, _ints(), lambda inp, out: out >= 0, trials=200, seed=1)
    assert res.ok and res.trials == 200 and res.passed == 200
    assert res.counterexample is None and res.detail is None
    assert isinstance(res, FuzzResult)


def test_fuzz_check_finds_property_counterexample():
    # Buggy "square": wrong (returns x) for negatives → property out == x*x breaks.
    def buggy(x):
        return x * x if x >= 0 else x
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
    def buggy(x):
        return x * x if x >= 0 else x

    def prop(inp, out):
        return out == inp * inp
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
    def baseline(x):
        return x * 2

    def candidate(x):
        return x + x
    res = differential_check(baseline, candidate, _ints(), trials=200, seed=1)
    assert res.ok and res.passed == 200 and res.counterexample is None


def test_differential_finds_divergence():
    def baseline(x):
        return x * 2

    def candidate(x):
        return x * 2 if x != 5 else 999  # diverges at 5
    res = differential_check(baseline, candidate, _ints(0, 10), trials=500, seed=2)
    assert res.ok is False and res.counterexample == 5
    assert "baseline=10" in (res.detail or "") and "candidate=999" in (res.detail or "")


def test_differential_same_exception_type_is_preserved_behaviour():
    # candidate (2/x) != baseline (1/x) on nonzero inputs → it diverges there.
    res = differential_check(lambda x: 1 / x, lambda x: 2 / x, _ints(-2, 2),
                             trials=300, seed=4)
    assert res.ok is False  # diverges on nonzero values
    # When they only ever hit 0, both raise ZeroDivisionError → behaviour preserved.
    res0 = differential_check(lambda x: 1 / x, lambda x: 5 / x, lambda rng: 0,
                              trials=10, seed=0)
    assert res0.ok is True


def test_differential_one_raises_other_returns_is_divergence():
    # Agree on every nonzero input (both 1/x); differ only at 0, where the baseline
    # returns and the candidate raises → the sole counterexample is 0.
    def baseline(x):
        return 0.0 if x == 0 else 1 / x   # handles 0, never raises

    def candidate(x):
        return 1 / x                       # raises on 0
    res = differential_check(baseline, candidate, _ints(-2, 2), trials=300, seed=11)
    assert res.ok is False and res.counterexample == 0
    assert "raised ZeroDivisionError" in (res.detail or "")


def test_differential_custom_equal_for_floats():
    def baseline(x):
        return x / 3.0

    def candidate(x):
        return x * (1.0 / 3.0)  # tiny float error
    strict = differential_check(baseline, candidate, _ints(1, 50), trials=200, seed=5)
    close = differential_check(baseline, candidate, _ints(1, 50), trials=200, seed=5,
                               equal=lambda a, b: math.isclose(a, b, rel_tol=1e-9))
    # strict == may or may not diverge depending on values; isclose must always hold.
    assert close.ok is True
    assert strict.seed == 5 and close.seed == 5


# ── generator vocabulary (B.4k polish) ──────────────────────────────


def test_gen_int_in_range_and_seeded():
    g = gen_int(0, 9)

    def draws(seed):
        rng = Random(seed)
        return [g(rng) for _ in range(20)]
    assert draws(3) == draws(3)   # same seed → identical sequence (reproducible)
    assert draws(3) != draws(4)   # different seeds diverge
    rng = Random(0)
    assert all(0 <= g(rng) <= 9 for _ in range(200))


def test_gen_float_in_range():
    rng = Random(1)
    assert all(-2.0 <= gen_float(-2.0, 2.0)(rng) <= 2.0 for _ in range(200))  # closed interval


def test_gen_bool_yields_both():
    rng = Random(2)
    seen = {gen_bool()(rng) for _ in range(50)}
    assert seen == {True, False}


def test_gen_choice_from_options_and_rejects_empty():
    rng = Random(3)
    assert all(gen_choice(("a", "b", "c"))(rng) in {"a", "b", "c"} for _ in range(50))
    with pytest.raises(ValueError, match="non-empty"):
        gen_choice([])


def test_gen_text_length_bounded_and_can_be_empty():
    rng = Random(4)
    samples = [gen_text(max_len=6)(rng) for _ in range(300)]
    assert all(0 <= len(s) <= 6 for s in samples)
    assert any(s == "" for s in samples)  # covers the empty-string edge


def test_gen_list_length_bounds_and_element_type():
    rng = Random(5)
    lists = [gen_list(gen_int(0, 3), min_len=1, max_len=4)(rng) for _ in range(200)]
    assert all(1 <= len(x) <= 4 for x in lists)
    assert all(all(0 <= e <= 3 for e in x) for x in lists)


def test_gen_tuple_shape():
    rng = Random(6)
    t = gen_tuple(gen_int(0, 0), gen_bool(), gen_choice(["x"]))(rng)
    assert t == (0, t[1], "x") and isinstance(t[1], bool) and len(t) == 3


def test_gen_one_of_unions_and_rejects_empty():
    rng = Random(8)
    vals = [gen_one_of(gen_int(0, 0), gen_choice(["s"]))(rng) for _ in range(80)]
    assert set(vals) == {0, "s"}
    with pytest.raises(ValueError, match="at least one"):
        gen_one_of()


def test_generators_compose_with_fuzz_check():
    # The vocabulary plugs straight into fuzz_check: a list of ints, sorted, stays
    # sorted and same-length (a real property over generated inputs).
    def prop(inp, out):
        return out == sorted(inp) and len(out) == len(inp)
    res = fuzz_check(sorted, gen_list(gen_int(-50, 50), max_len=10), prop,
                     trials=300, seed=0)
    assert res.ok, res
