"""Witness-panel calibration analysis (ADR 0187 #4) — pure, offline."""

from __future__ import annotations

from chimera.core.witness import WitnessVerdict
from chimera.core.witness_calibration import (
    member_stats,
    panel_confusion,
    vote_agreement,
)


def _v(approved: bool, concerns=None) -> WitnessVerdict:
    return WitnessVerdict(approved=approved, concerns=concerns or [])


def test_member_stats_confusion():
    labels = [True, True, False, False]
    verdicts = [_v(True), _v(False), _v(False), _v(True)]
    s = member_stats("m", verdicts, labels)
    assert s.n == 4
    assert s.correct == 2            # case0 (T==T), case2 (F==F)
    assert s.false_reject == 1       # case1: rejected a should-approve
    assert s.false_approve == 1      # case3: approved a should-reject (dangerous)
    assert s.accuracy == 0.5


def test_vote_agreement():
    a = [_v(True), _v(True), _v(False)]
    b = [_v(True), _v(False), _v(False)]
    assert vote_agreement(a, b) == 2 / 3   # agree on cases 0 and 2
    assert vote_agreement(a, a) == 1.0     # identical voter
    assert vote_agreement([], []) == 0.0


def test_panel_confusion_majority():
    labels = [True, False]
    # case0: all approve → approve (correct). case1: 2 reject, 1 approve → reject (correct).
    m1 = [_v(True), _v(True)]
    m2 = [_v(True), _v(False)]
    m3 = [_v(True), _v(False)]
    c = panel_confusion([m1, m2, m3], labels)
    assert c["correct"] == 2 and c["false_approve"] == 0 and c["false_reject"] == 0
    assert c["accuracy"] == 1.0


def test_panel_confusion_charter_override_rejects():
    # A single charter/security dissent rejects regardless of the majority.
    labels = [True]  # the change should be approved
    m1 = [_v(True)]
    m2 = [_v(True)]
    m3 = [_v(False, concerns=["this crosses a security boundary"])]
    c = panel_confusion([m1, m2, m3], labels)
    assert c["false_reject"] == 1 and c["correct"] == 0  # charter override fired


def test_panel_confusion_catches_bad_change():
    # A should-reject change that the majority rejects → caught (no false-approve).
    labels = [False]
    m1 = [_v(False)]
    m2 = [_v(False)]
    m3 = [_v(True)]
    c = panel_confusion([m1, m2, m3], labels)
    assert c["false_approve"] == 0 and c["correct"] == 1


# ── error handling: a None (provider error) is EXCLUDED, never counted approve ─


def test_member_stats_excludes_errors():
    labels = [True, False, True, False]
    # case1 (should-reject) errored — must NOT become a fabricated false-approve.
    verdicts = [_v(True), None, _v(True), _v(False)]
    s = member_stats("m", verdicts, labels)
    assert s.errors == 1
    assert s.n == 3                  # answered, not 4
    assert s.false_approve == 0      # the errored should-reject is excluded
    assert s.correct == 3            # cases 0, 2, 3 all correct
    assert s.accuracy == 1.0         # over ANSWERED cases only


def test_vote_agreement_excludes_error_pairs():
    a = [_v(True), None, _v(False)]
    b = [_v(True), _v(True), None]
    # Only case0 has both present → 100% over the comparable case.
    assert vote_agreement(a, b) == 1.0


def test_panel_confusion_skips_all_error_case_and_drops_voters():
    labels = [True, False]
    # case0: only m1 answers (others errored) → panel = m1's approve (correct).
    # case1: all errored → skipped.
    m1 = [_v(True), None]
    m2 = [None, None]
    m3 = [None, None]
    c = panel_confusion([m1, m2, m3], labels)
    assert c["skipped"] == 1 and c["n"] == 1 and c["correct"] == 1
