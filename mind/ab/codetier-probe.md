---
goal: "Add chimera.core.duration.parse_duration — parse a compound duration string into seconds"
files: chimera/core/duration.py tests/test_duration.py
test: tests/test_duration.py
base: main
done: false  # A/B PROBE — never merged; ab_soak.sh runs both model arms against it
---
A/B PROBE for ADR 0183 A.1 (NOT a daily-CRAWL task — it lives outside
`mind/backlog/` so the picker never auto-runs it; `scripts/ab_soak.sh` runs it
on both model arms). It stays red on `base` (never merged), so the A/B is
repeatable: re-run it whenever a new code model is ingested.

The task is a single self-contained pure function — moderately tricky (regex,
ordering + dedup validation, a spread of error cases) so two models genuinely
differentiate, but with FIXED acceptance criteria so both arms build the same
behaviour and only the model varies.

Implement `chimera/core/duration.py` with:

    def parse_duration(text: str) -> int:
        """Parse a compound duration like "1h30m" into a whole number of
        seconds. Returns the total seconds (int)."""

Behaviour (this IS the spec — the agent's own test must pin all of it):

- Units: `d` (86400s), `h` (3600s), `m` (60s), `s` (1s). Case-insensitive
  (`"1H30M"` == `"1h30m"`).
- A token is `<non-negative-integer><unit>`; a value may be multi-digit and
  zero (`"0s"` → 0). The string is one or more concatenated tokens.
- Surrounding/internal ASCII whitespace is tolerated and ignored
  (`" 1h 30m "` → 5400).
- Units MUST appear in strictly descending magnitude order (d > h > m > s)
  with NO repeats. `"30m1h"` (out of order) and `"1h1h"` (repeat) both raise
  `ValueError`.
- Examples that MUST hold:
  `"90s"` → 90; `"2d"` → 172800; `"1h30m"` → 5400; `"1h30m15s"` → 5415;
  `"1d2h3m4s"` → 93784; `"0s"` → 0.
- `ValueError` (not a bare/other exception) on: empty/whitespace-only input,
  a non-string, a bare number with no unit (`"120"`), an unknown unit
  (`"5x"`), a negative or non-integer value (`"-5s"`, `"1.5h"`), and any
  unparseable trailing/leading junk (`"1h foo"`).

Acceptance: create `tests/test_duration.py` covering every bullet above
(each happy-path example AND each ValueError case — a discriminating test per
behaviour, not one smoke test). `chimera verify` (ruff over the two files +
the new test) is GREEN. Keep the change to exactly the two scoped files; the
function must be pure (no I/O, no globals, no third-party deps).
