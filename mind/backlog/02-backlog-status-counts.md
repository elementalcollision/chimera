---
goal: "Add a count_by_status(mind_dir) helper to chimera.core.backlog"
files: chimera/core/backlog.py tests/test_backlog_status_counts.py
test: tests/test_backlog_status_counts.py
base: main
done: false
---
Useful backlog overview for the dashboard / `chimera backlog list` header:
add `count_by_status(mind_dir) -> dict[str, int]` returning counts keyed
"ready" (valid, not done), "done", and "invalid" over the specs in the
backlog dir. Reuse the existing `list_specs`; do not change selection logic.

Acceptance: create `tests/test_backlog_status_counts.py` covering a mixed
backlog (one ready, one done, one invalid → {"ready":1,"done":1,"invalid":1})
and an empty backlog ({"ready":0,"done":0,"invalid":0}). Keep the change in
chimera/core/backlog.py. `chimera verify` green.
