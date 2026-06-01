"""Stateful characterization (ADR 0159 complement): the differential, for classes.

The stateful validation (2026-06-01) showed the pure-function differential is
blind on a class whose behaviour depends on call SEQUENCE. This drives the class
through scenarios + snapshots observer state, catching exactly the accumulation
bug the pure corpus missed.
"""

from __future__ import annotations

from chimera.core.stateful_diff import (
    Scenario,
    StatefulReport,
    observer_methods,
    stateful_delta,
)

# Correct accumulator vs the validation's buggy version (self._sum = x).
_CORRECT = (
    "class RunningStats:\n"
    "    def __init__(self):\n        self._count=0; self._sum=0.0\n"
    "    def add(self, x):\n        self._sum += x; self._count += 1\n"
    "    def count(self):\n        return self._count\n"
    "    def mean(self):\n        return 0.0 if self._count==0 else self._sum/self._count\n"
)
_BUGGY = _CORRECT.replace("self._sum += x", "self._sum = x")

_SEQ = Scenario("add-three", [("add", (2.0,)), ("add", (4.0,)), ("add", (6.0,))])
_ONE = Scenario("add-one", [("add", (10.0,))])


# ── headline: catches what the pure differential could not ───────────


def test_catches_stateful_accumulation_bug():
    rep = stateful_delta(_BUGGY, _CORRECT, "RunningStats", [_SEQ, _ONE])
    assert rep.behaviour_changed
    changed = {d.scenario for d in rep.changed}
    assert "add-three" in changed          # sequence reveals the bug
    assert "add-one" not in changed        # single add is identical (mean==value)
    assert "mean=2.0" in rep.summary() or "mean=4.0" in rep.summary()
    assert "STATEFUL DELTA" in rep.summary()


def test_identical_source_no_delta():
    rep = stateful_delta(_CORRECT, _CORRECT, "RunningStats", [_SEQ])
    assert rep.behaviour_changed is False
    assert "NO STATEFUL DELTA" in rep.summary()


# ── observer discovery ───────────────────────────────────────────────


def test_observer_methods_are_zero_arg_public():
    obs = observer_methods(_CORRECT, "RunningStats")
    assert set(obs) == {"count", "mean"}   # add(x) excluded (takes an arg)


def test_observer_methods_missing_class_is_empty():
    assert observer_methods(_CORRECT, "Nope") == []


# ── robustness: never raise ──────────────────────────────────────────


def test_call_that_raises_is_captured_not_raised():
    src = ("class C:\n    def __init__(self):\n        self.n=0\n"
           "    def go(self, x):\n        return 10 // x\n")
    base = src
    new = src.replace("return 10 // x", "return 0 if x==0 else 10 // x")
    sc = Scenario("div", [("go", (0,)), ("go", (5,))])
    rep = stateful_delta(base, new, "C", [sc], observers=[])
    assert rep.behaviour_changed
    assert "raised:ZeroDivisionError" in rep.changed[0].before


def test_uncompilable_base_is_error_marker():
    rep = stateful_delta("class C(:\n bad", _CORRECT, "RunningStats", [_SEQ])
    assert rep.behaviour_changed
    assert rep.changed[0].before.startswith("error:")


def test_missing_constructor_arg_is_error_not_raise():
    src = "class C:\n    def __init__(self, required):\n        self.x=required\n"
    rep = stateful_delta(src, src, "C", [Scenario("s", [])], observers=[])
    # ctor needs an arg → ctor error, identical both sides → no delta, no raise
    assert rep.behaviour_changed is False


def test_report_defaults():
    r = StatefulReport(class_name="X")
    assert r.total == 0 and r.behaviour_changed is False


# ── auto-scenario generation (usable without hand-written sequences) ──


def test_auto_scenarios_drive_mutating_methods():
    from chimera.core.stateful_diff import auto_scenarios
    scs = auto_scenarios(_CORRECT, "RunningStats", repeats=3)
    assert len(scs) == 1                       # only add() is a mutator
    sc = scs[0]
    assert sc.name == "addx3"
    assert [c[0] for c in sc.calls] == ["add", "add", "add"]
    assert [c[1] for c in sc.calls] == [(1.0,), (2.0,), (3.0,)]  # float ann → 1.0,2.0,3.0


def test_auto_scenarios_close_the_stateful_gap_end_to_end():
    from chimera.core.stateful_diff import auto_scenarios
    scs = auto_scenarios(_CORRECT, "RunningStats")
    rep = stateful_delta(_BUGGY, _CORRECT, "RunningStats", scs)
    assert rep.behaviour_changed               # caught with NO hand-written scenario
    assert "mean=1.0" in rep.summary() and "mean=2.0" in rep.summary()


def test_auto_scenarios_no_mutators_is_empty():
    src = "class C:\n    def __init__(self):\n        self.x=1\n    def get(self):\n        return self.x\n"
    from chimera.core.stateful_diff import auto_scenarios
    assert auto_scenarios(src, "C") == []
