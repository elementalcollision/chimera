"""Critic calibration harness (no-contract trust): measure the critic's error
rates, especially the false-APPROVE rate (waving an unfaithful change through).

The confusion-matrix math is pinned with a mock reviewer (deterministic); the
dataset is checked for balance and authentic diffs/faithfulness. The live run
against the real provider is an operator action (the `chimera critic-calibrate`
verb).
"""

from __future__ import annotations

import asyncio

from chimera.core.critic import CriticVerdict
from chimera.core.critic_calibration import (
    CalibrationResult,
    build_case,
    default_cases,
    run_calibration,
)


def _verdict(approved: bool) -> CriticVerdict:
    return CriticVerdict(approved=approved)


def _run(cases, review_fn):
    return asyncio.run(run_calibration(cases, review_fn))


# ── confusion-matrix math (mock reviewers) ───────────────────────────


def test_perfect_reviewer_scores_full_accuracy():
    cases = default_cases()
    async def perfect(c):
        return _verdict(c.should_approve)
    res = _run(cases, perfect)
    assert res.accuracy == 1.0
    assert res.false_approve == 0 and res.false_reject == 0
    assert res.false_approve_rate == 0.0


def test_approve_everything_exposes_false_approves():
    cases = default_cases()
    async def yes(c):
        return _verdict(True)
    res = _run(cases, yes)
    n_should_reject = sum(1 for c in cases if not c.should_approve)
    assert res.false_approve == n_should_reject
    assert res.false_approve_rate == 1.0   # every unfaithful change waved through
    assert res.false_reject == 0


def test_reject_everything_exposes_false_rejects():
    cases = default_cases()
    async def no(c):
        return _verdict(False)
    res = _run(cases, no)
    n_should_approve = sum(1 for c in cases if c.should_approve)
    assert res.false_reject == n_should_approve
    assert res.false_approve == 0
    assert res.false_reject_rate == 1.0


def test_summary_reports_rates_and_dangerous_marker():
    cases = default_cases()
    async def yes(c):
        return _verdict(True)
    s = _run(cases, yes).summary()
    assert "false-APPROVE rate" in s
    assert "dangerous" in s


def test_result_math_on_hand_built_outcomes():
    # 1 TP, 1 TN, 1 FP, 1 FN
    from chimera.core.critic_calibration import CaseOutcome
    def case(ok):
        return build_case("x", "g", "def f(s):\n return s\n",
                          "def f(s):\n return s\n", "f", "d", ok, "k")
    res = CalibrationResult(outcomes=[
        CaseOutcome(case(True), approved=True, correct=True),    # TP
        CaseOutcome(case(False), approved=False, correct=True),  # TN
        CaseOutcome(case(False), approved=True, correct=False),  # FP
        CaseOutcome(case(True), approved=False, correct=False),  # FN
    ])
    assert res.true_approve == 1 and res.true_reject == 1
    assert res.false_approve == 1 and res.false_reject == 1
    assert res.accuracy == 0.5
    assert res.false_approve_rate == 0.5   # 1 FP / (1 FP + 1 TN)
    assert res.false_reject_rate == 0.5


# ── dataset authenticity ─────────────────────────────────────────────


def test_default_cases_are_balanced():
    cases = default_cases()
    approve = [c for c in cases if c.should_approve]
    reject = [c for c in cases if not c.should_approve]
    assert len(approve) >= 2 and len(reject) >= 2


def test_default_cases_carry_authentic_diff_and_faithfulness():
    for c in default_cases():
        assert c.diff.strip().startswith("---")  # a real unified diff
        assert "@@" in c.diff
        assert c.faithfulness  # non-empty report
        assert c.docstring


def test_isdigit_drop_case_shows_behaviour_delta():
    drop = next(c for c in default_cases() if c.case_id == "snake-isdigit-drop")
    # the differential surfaced the regression in the faithfulness report
    assert "DELTA" in drop.faithfulness
    assert "foo2" in drop.faithfulness
