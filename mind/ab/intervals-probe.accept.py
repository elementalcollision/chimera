"""Canonical acceptance test — intervals-probe (HARD). See mind/ab/README.md.

Normalises each arm's output to a list of tuples before comparing, so an arm
returning lists-of-lists isn't penalised for container type — only the merge
semantics are graded.
"""

from __future__ import annotations

import pytest

from chimera.core.intervals import merge_intervals


def _norm(result):
    return [tuple(x) for x in result]


HAPPY = [
    ([], []),
    ([(1, 3)], [(1, 3)]),
    ([(1, 3), (2, 6), (8, 10), (15, 18)], [(1, 6), (8, 10), (15, 18)]),
    ([(1, 4), (4, 5)], [(1, 5)]),               # touching merges
    ([(1, 4), (5, 6)], [(1, 4), (5, 6)]),        # gap stays split
    ([(6, 8), (1, 9), (2, 4), (4, 7)], [(1, 9)]),  # unsorted, full overlap
    ([(1, 4), (0, 4)], [(0, 4)]),                # unsorted, contained
    ([(1, 1), (1, 1)], [(1, 1)]),                # degenerate points
]


@pytest.mark.parametrize("intervals,expected", HAPPY)
def test_happy(intervals, expected):
    assert _norm(merge_intervals(list(intervals))) == expected


@pytest.mark.parametrize("bad", [
    "nope", None, 42,            # not a list
    [(3, 1)],                    # start > end
    [(1,)],                      # not a pair
    [(1, 2, 3)],                 # not a pair
    [(1, "x")],                  # non-int bound
    [1, 2],                      # element not a pair
    [(True, 3)],                 # bool bound
])
def test_raises_value_error(bad):
    with pytest.raises(ValueError):
        merge_intervals(bad)  # type: ignore[arg-type]
