---
goal: "Add HealthSummary.from_dict() — inverse of to_dict (round-trippable)"
files: chimera/core/health.py tests/test_health_from_dict.py
test: tests/test_health_from_dict.py
property: "HealthSummary.from_dict(s.to_dict()) == s for any summary s (round-trip identity, dimensions included)"
base: main
done: true
---
Add a `from_dict(data: dict) -> HealthSummary` classmethod to `HealthSummary`
that reconstructs a summary from the shape produced by `to_dict()` — so a
health snapshot can be persisted to JSON and reloaded. It must round-trip:
`HealthSummary.from_dict(s.to_dict()) == s` for any summary `s` (including its
`HealthDimension` list).

Implement as the exact inverse of the existing `to_dict()` (inspect that method
for the key names / nesting); rebuild the `HealthDimension` objects too. No
change to `compute_health`.

Acceptance: create `tests/test_health_from_dict.py` covering: a multi-dimension
summary round-trips (`from_dict(to_dict()) == original`, dimensions included);
an all-green/empty summary round-trips. Keep the change in
`chimera/core/health.py`. `chimera verify` (ruff + the new test) green.
