---
goal: "Add HealthSummary.alert_line() — terse one-line health alert string"
files: chimera/core/health.py tests/test_health_alert_line.py
test: tests/test_health_alert_line.py
base: main
done: true  # landed 2026-06-19 — qwen CRAWL deliverable (run realtask-2026-06-19-2014)
---
Build on `worst_dimensions()` (landed): add an `alert_line()` method to
`HealthSummary` returning a single terse string for alerts/logs.

Behaviour:
- overall `green` → `"OK"`; overall `unknown` → `"UNKNOWN"` (no drivers).
- otherwise → `"<LABEL>: <key1>, <key2>"` where the keys are
  `worst_dimensions()`'s dimension keys in their existing order, and LABEL maps
  the overall status: `red` → `DEGRADED`, `amber` → `WATCH`.
  e.g. a red summary driven by drift + escalations → `"DEGRADED: drift, escalations"`.

Pure method; reuse `worst_dimensions()`; no change to `compute_health`.

Acceptance: create `tests/test_health_alert_line.py` covering: a `red` summary
with two red dims → `"DEGRADED: <k1>, <k2>"`; an `amber` summary → `"WATCH: ..."`;
all-green → `"OK"`; unknown → `"UNKNOWN"`. Keep the change in
`chimera/core/health.py`. `chimera verify` (ruff + the new test) green.
