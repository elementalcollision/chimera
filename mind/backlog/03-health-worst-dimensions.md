---
goal: "Add HealthSummary.worst_dimensions() to chimera.core.health"
files: chimera/core/health.py tests/test_health_worst_dimensions.py
test: tests/test_health_worst_dimensions.py
base: main
done: false
---
Terse alerting helper: add a `worst_dimensions()` method to `HealthSummary`
returning the list of `HealthDimension`s whose status equals the overall
verdict (i.e. the ones driving a WATCH/DEGRADED) — empty when overall is
green/unknown. Lets an alert show "DEGRADED: drift, fragmentation" without
re-deriving. Pure method, no change to compute_health.

Acceptance: create `tests/test_health_worst_dimensions.py` covering: a
summary with one red + one amber dim → worst_dimensions() returns just the
red one; an all-green summary → []. Keep the change in chimera/core/health.py.
`chimera verify` green.
