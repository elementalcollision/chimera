"""Canonical acceptance test for the codetier-probe A/B (ADR 0183 A.1).

NOT a daily-suite test (it lives under mind/, not tests/). `ab_soak.sh` copies
it into each arm's worktree after the soak and runs it against that arm's
produced `chimera/core/duration.py`, so BOTH arms are graded on the IDENTICAL
external spec — the quality control the in-loop (self-authored) gate cannot
provide. Verdict: highest spec-pass wins; cost breaks ties at equal quality.

This file is the single source of truth for the probe's acceptance criteria —
it mirrors the bullets in `mind/ab/codetier-probe.md`.
"""

from __future__ import annotations

import pytest

from chimera.core.duration import parse_duration

HAPPY = {
    "90s": 90,
    "2d": 172800,
    "1h30m": 5400,
    "1h30m15s": 5415,
    "1d2h3m4s": 93784,
    "0s": 0,
    "1H30M": 5400,        # case-insensitive
    " 1h 30m ": 5400,     # whitespace tolerated
}

RAISERS = [
    "",                   # empty
    "   ",                # whitespace-only
    "120",                # bare number, no unit
    "5x",                 # unknown unit
    "-5s",                # negative
    "1.5h",               # fractional
    "1h foo",             # trailing junk
    "30m1h",              # out of order
    "1h1h",               # repeated unit
]


@pytest.mark.parametrize("text,expected", HAPPY.items())
def test_happy(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", RAISERS)
def test_raises_value_error(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_non_string_raises_value_error():
    with pytest.raises(ValueError):
        parse_duration(None)  # type: ignore[arg-type]
