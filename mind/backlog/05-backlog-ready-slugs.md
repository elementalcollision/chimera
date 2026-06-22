---
goal: "Add backlog.ready_slugs(mind_dir) — slugs of all actionable specs"
files: chimera/core/backlog.py tests/test_backlog_ready_slugs.py
test: tests/test_backlog_ready_slugs.py
base: main
done: true
---
Add a module-level `ready_slugs(mind_dir) -> list[str]` to
`chimera.core.backlog` returning the slugs of every spec that is actionable —
**valid AND not done** — in `list_specs` order (oldest-first). It mirrors
`select_next`'s filter but returns the whole ready queue rather than just the
first, for a queue preview / dashboard header.

Reuse `list_specs()`; do not re-implement parsing.

Acceptance: create `tests/test_backlog_ready_slugs.py` (use `tmp_path` for a
backlog dir) covering: a dir with one ready spec, one `done: true` spec, and
one invalid spec → only the ready spec's slug is returned; an empty/missing
dir → `[]`. Keep the change in `chimera/core/backlog.py`. `chimera verify`
(ruff + the new test) green.
