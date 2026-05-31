"""Differential behaviour check (ADR 0159 complement): catch DELETED behaviour
the mutation gate is structurally blind to.

The first live soak's agent dropped `or s[i-1].isdigit()` from to_snake — a
removed method-call clause with no mutation site. The differential runs the
function over a corpus under both versions and flags where output changed; a
delta on an untested input is a candidate silent regression. The headline test
reproduces the EXACT regression: comparing the correct to_snake against the
agent's isdigit-dropped fix surfaces the digit-adjacent inputs.
"""

from __future__ import annotations

from chimera.core.differential import (
    DifferentialReport,
    behavioral_delta,
    default_string_corpus,
)

# Correct to_snake (with the digit clause) vs the agent's fix (clause dropped).
_CORRECT = (
    "def to_snake(s):\n"
    "    r=[]\n"
    "    for i,ch in enumerate(s):\n"
    "        if ch.isupper() and i>0 and (s[i-1].islower() or s[i-1].isdigit()):\n"
    "            r.append('_')\n"
    "        r.append(ch.lower())\n"
    "    return ''.join(r)\n"
)
_AGENT_FIX = _CORRECT.replace(" or s[i-1].isdigit()", "")


# ── the headline: catches the exact deletion mutation missed ─────────


def test_catches_isdigit_deletion_regression():
    rep = behavioral_delta(_CORRECT, _AGENT_FIX, "to_snake", default_string_corpus())
    assert rep.behaviour_changed
    changed_inputs = {d.args[0] for d in rep.changed}
    # digit-adjacent inputs regress; non-digit inputs are untouched
    assert "foo2Bar" in changed_inputs
    assert "a1B2c3" in changed_inputs
    assert "CamelCase" not in changed_inputs
    assert "BEHAVIOUR DELTA" in rep.summary()
    assert "foo2_bar" in rep.summary() and "foo2bar" in rep.summary()


def test_identical_behaviour_no_delta():
    rep = behavioral_delta(_CORRECT, _CORRECT, "to_snake", default_string_corpus())
    assert rep.behaviour_changed is False
    assert rep.changed == []
    assert "NO BEHAVIOUR DELTA" in rep.summary()


# ── primitive semantics ──────────────────────────────────────────────


def test_delta_records_before_and_after():
    base = "def f(x):\n    return x + 1\n"
    new = "def f(x):\n    return x + 2\n"
    rep = behavioral_delta(base, new, "f", [(1,), (10,)])
    assert rep.total == 2
    assert len(rep.changed) == 2
    d = rep.changed[0]
    assert d.before == "2" and d.after == "3"


def test_raised_exception_is_observable_behaviour():
    # base raises on 0; new guards it → the behaviour on (0,) differs
    base = "def f(x):\n    return 10 // x\n"
    new = "def f(x):\n    return 0 if x == 0 else 10 // x\n"
    rep = behavioral_delta(base, new, "f", [(0,), (5,)])
    changed = {d.args: (d.before, d.after) for d in rep.changed}
    assert (0,) in changed
    assert changed[(0,)][0] == "raised:ZeroDivisionError"
    assert (5,) not in changed  # 10//5 == 2 unchanged


def test_uncompilable_source_is_error_marker_not_raise():
    rep = behavioral_delta("def f(:\n bad", "def f(x):\n return x", "f", [(1,)])
    # base fails to compile → "error:..."; new returns "1" → delta, no exception
    assert rep.behaviour_changed
    assert rep.changed[0].before.startswith("error:")


def test_report_dataclass_defaults():
    r = DifferentialReport(fn_name="g")
    assert r.total == 0 and r.behaviour_changed is False


def test_corpus_includes_digit_adjacent_cases():
    flat = {c[0] for c in default_string_corpus()}
    assert {"foo2Bar", "a1B2c3", "2leading", "trailing2"} <= flat
