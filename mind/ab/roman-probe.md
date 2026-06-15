---
goal: "Add chimera.core.roman — to_roman/from_roman with validation (round-trippable)"
files: chimera/core/roman.py tests/test_roman.py
test: tests/test_roman.py
base: main
done: false  # A/B PROBE (MEDIUM-HARD) — never merged; graded by roman-probe.accept.py
---
A/B PROBE for ADR 0183 A.1 — **MEDIUM-HARD** tier (bidirectional algorithm +
validation both directions). Outside `mind/backlog/`. Graded against
`roman-probe.accept.py`.

Implement `chimera/core/roman.py` with two pure functions:

    def to_roman(n: int) -> str:     # 1..3999 → standard Roman numeral
    def from_roman(s: str) -> int:   # valid Roman numeral → int

Behaviour (FIXED — the accept test is the source of truth):

- `to_roman`: standard subtractive form. `1→"I"`, `4→"IV"`, `9→"IX"`,
  `58→"LVIII"`, `1994→"MCMXCIV"`, `3999→"MMMCMXCIX"`. `ValueError` on a
  non-`int` (incl. `bool`), or out of `1..3999` (`0`, `-1`, `4000`).
- `from_roman`: parse a *well-formed* uppercase numeral → int. `"IV"→4`,
  `"MCMXCIV"→1994`, `"MMMCMXCIX"→3999`. `ValueError` on a non-`str`, empty,
  or malformed numeral — reject `"IIII"`, `"VV"`, `"IL"`, `"abc"`, lowercase.
- Round-trip: `from_roman(to_roman(n)) == n` for all `n` in `1..3999`.

Acceptance: create `tests/test_roman.py` covering both directions, the error
cases, and the round-trip property. `chimera verify` (ruff + the new test)
GREEN. Pure functions, no I/O.
