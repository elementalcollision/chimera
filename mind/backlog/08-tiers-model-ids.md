---
goal: "Add tiers.tier_model_ids(tier) — model ids of a tier ladder in escalation order"
files: chimera/providers/tiers.py tests/test_tier_model_ids.py
test: tests/test_tier_model_ids.py
base: main
done: true
---
Add `tier_model_ids(tier: str) -> list[str]` to `chimera.providers.tiers`
returning the `model_id` of each rung in the tier's ladder, in escalation
(cheapest-first) order. Raise `ValueError` for an unknown tier, mirroring
`select_rung`/`eligible_rungs`. Introspection helper for dashboards / `chimera
tiers` callers that want ids without walking `LadderRung` objects.

Reuse `TIER_LADDERS` (or `eligible_rungs`); do not hardcode model names.

Acceptance: create `tests/test_tier_model_ids.py` covering: `tier_model_ids("code")`
equals the live CODE_LADDER ids in order (first is `qwen/qwen3.7-max`, last is
the claude-opus safety-net); an unknown tier raises `ValueError`. Derive the
expected list from `CODE_LADDER` (don't hardcode) so it can't drift. Keep the
change in `chimera/providers/tiers.py`. `chimera verify` (ruff + the new test) green.
