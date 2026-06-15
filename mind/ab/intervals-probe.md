---
goal: "Add chimera.core.intervals.merge_intervals — merge overlapping/adjacent integer intervals"
files: chimera/core/intervals.py tests/test_intervals.py
test: tests/test_intervals.py
base: main
done: false  # A/B PROBE (HARD) — never merged; graded by intervals-probe.accept.py
---
A/B PROBE for ADR 0183 A.1 — **HARD** tier (list algorithm + structural
validation). Outside `mind/backlog/`. Graded against
`intervals-probe.accept.py`.

Implement `chimera/core/intervals.py`:

    def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Merge overlapping or touching intervals; return them sorted,
        non-overlapping, as a list of (start, end) tuples."""

Behaviour (FIXED — the accept test is the source of truth):

- Input is a list of `(start, end)` pairs (each a 2-element list or tuple).
  Output is a list of `(start, end)` **tuples**, sorted by start, with all
  overlapping OR touching intervals merged.
- Touching merges: `[(1,4),(4,5)]` → `[(1,5)]`. Gaps don't: `[(1,4),(5,6)]`
  → `[(1,4),(5,6)]`.
- Examples: `[(1,3),(2,6),(8,10),(15,18)]` → `[(1,6),(8,10),(15,18)]`;
  `[(6,8),(1,9),(2,4),(4,7)]` → `[(1,9)]`; `[]` → `[]`; `[(1,3)]` → `[(1,3)]`.
- `ValueError` on: a non-list; an element that isn't a 2-element pair; a
  non-`int` bound (incl. `bool`); an interval with `start > end`.

Acceptance: create `tests/test_intervals.py` covering merging, touching vs
gap, ordering of unsorted input, and every error case. `chimera verify`
(ruff + the new test) GREEN. Pure function, no I/O.
