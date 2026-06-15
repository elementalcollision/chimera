"""Canonical acceptance test — roman-probe (MEDIUM-HARD). See mind/ab/README.md."""

from __future__ import annotations

import pytest

from chimera.core.roman import from_roman, to_roman

TO_ROMAN = {
    1: "I", 4: "IV", 9: "IX", 14: "XIV", 40: "XL", 58: "LVIII", 90: "XC",
    400: "CD", 944: "CMXLIV", 1994: "MCMXCIV", 2024: "MMXXIV", 3999: "MMMCMXCIX",
}


@pytest.mark.parametrize("n,expected", TO_ROMAN.items())
def test_to_roman(n, expected):
    assert to_roman(n) == expected


@pytest.mark.parametrize("s,expected", {v: k for k, v in TO_ROMAN.items()}.items())
def test_from_roman(s, expected):
    assert from_roman(s) == expected


@pytest.mark.parametrize("bad", [0, -1, 4000, 5000, True, 1.5, "5", None])
def test_to_roman_rejects(bad):
    with pytest.raises(ValueError):
        to_roman(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "IIII", "VV", "IL", "abc", "mcmxciv", "XIIX", 5, None])
def test_from_roman_rejects(bad):
    with pytest.raises(ValueError):
        from_roman(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [1, 2, 3, 4, 9, 40, 90, 444, 1666, 2999, 3888, 3999])
def test_round_trip(n):
    assert from_roman(to_roman(n)) == n
