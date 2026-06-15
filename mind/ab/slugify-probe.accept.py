"""Canonical acceptance test — slugify-probe (EASY). See mind/ab/README.md."""

from __future__ import annotations

import pytest

from chimera.core.slugify import slugify

HAPPY = {
    "Hello World": "hello-world",
    "  Multiple   Spaces  ": "multiple-spaces",
    "Already-slug": "already-slug",
    "Foo_Bar.Baz": "foo-bar-baz",
    "100% Pure!": "100-pure",
    "café": "caf",
    "a": "a",
    "UPPER": "upper",
    "--Leading and trailing--": "leading-and-trailing",
}

RAISERS = ["", "   ", "!!!", "   ---   "]


@pytest.mark.parametrize("text,expected", HAPPY.items())
def test_happy(text, expected):
    assert slugify(text) == expected


@pytest.mark.parametrize("text", RAISERS)
def test_raises_value_error(text):
    with pytest.raises(ValueError):
        slugify(text)


@pytest.mark.parametrize("bad", [None, 123, ["a"]])
def test_non_string_raises_value_error(bad):
    with pytest.raises(ValueError):
        slugify(bad)  # type: ignore[arg-type]
