---
goal: "EXAMPLE — fix a deprecated API call in a single test file"
files: tests/test_example.py
test: tests/test_example.py
base: main
done: true
---
This is a worked example, not a live task (done: true keeps it inert).

A real spec describes one small, low-risk maintenance change:
- `goal` is the one-line task (becomes the INBOX line).
- `files` is the tight allowlist the change may touch (also the ruff scope
  and the commit allowlist).
- `test` narrows the gate; for a warning-only fix make it red on base, e.g.
  `tests/test_example.py` run under `-W error`.
- The picker rejects this spec if its gate is already GREEN on `base`
  (gate-visibility, ADR 0182) — a change that proves nothing.
