# ADR 0125 — Wire the Deriver into ReflectionEngine

**Status**: Accepted (2026-05-24)

**Relationship**: Implements the follow-up wiring deferred by [ADR 0124](./0124-deriver-style-extraction.md). Phase 2 of the [ADR 0123](./0123-honcho-inspired-enhancements.md) roadmap.

## Context

ADR 0124 landed the deriver as a parser-only module: `ReflectionConclusions` schema + `parse_conclusions` + `build_deriver_prompt`, with no engine integration. That kept the schema/parser PR small and provider-agnostic. The follow-up — actually running the deriver — is now overdue.

The constraints are tight:

1. **Backward-compatible by default.** The reflection engine fires every evening; doubling its API spend without a switch is unacceptable.
2. **Deriver failure must not fail the reflection.** Prose is the load-bearing output; structured conclusions are a bonus signal. A failed `json.loads` or a 5xx on the second call must not roll back the prose chronicle write.
3. **Persistence must be append-only.** Multiple days accumulate without read-modify-write contention; format must survive concurrent operator inspection.

## Decision

Add an opt-in deriver pass to [`ReflectionEngine`](../../chimera/engines/reflection.py):

- **Env flag**: `CHIMERA_REFLECTION_DERIVER=1` (default off). Accepts `1`, `true`, `yes`, `on` (case-insensitive).
- **Call shape**: after the prose call succeeds, make a second call to the same provider/model with `build_deriver_prompt(day_so_far)`, parse with `parse_conclusions`, and persist on success.
- **Persistence**: append a JSONL row to `mind/reflection_conclusions.jsonl`. One row per cycle. Schema:

  ```json
  {"cycle": 7, "at": "<iso>", "summary": "...", "lessons_learned": [...],
   "improvements_for_tomorrow": [...], "themes": [...]}
  ```

- **Failure isolation**: the deriver call is wrapped in `try/except`. Any exception is logged at WARNING and the reflection still returns `success`. Empty conclusions (unparseable model output) bill the API call but write no row.
- **Telemetry**: the second API call is recorded in `api_calls` with `caller="reflection.deriver"`, and `engine_runs.api_calls` reflects both calls (1 → 2 when the deriver fires).

## Consequences

### Positive

- Downstream code (dashboards, escalation memory, future witness panels) can now query a typed daily signal without re-running an LLM.
- The flag-off default preserves every existing reflection test's behavior; no migration cost.
- Append-only JSONL is operator-friendly (`tail -f`, `jq`) and tolerant of crash-mid-write (only the in-flight line is lost; previous rows survive).

### Negative

- When enabled, reflection cost roughly doubles per cycle (two sonnet calls instead of one). Mitigated by being opt-in and by the deriver call being short — the prompt fits in a few hundred tokens and the response is bounded by the schema cap (5 items per list).
- A second `api_calls` row per reflection complicates cost reporting until callers learn to group by `caller`. Mitigated by the existing `caller` column already being indexed.

## Out of scope (this PR)

- A separate cost cap for the deriver call — falls under the existing per-cycle and rolling-hour caps.
- Surfacing `ReflectionConclusions` in `chimera doctor` / `chimera cost` widgets — follow-up.
- Reading `reflection_conclusions.jsonl` from the discovery/curiosity engines — follow-up.
- Switching the default from off to on — needs operator sign-off after a soak with the flag enabled.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md).
- [ADR 0124 — Deriver-style structured-output extraction](./0124-deriver-style-extraction.md) — parser + schema this PR wires up.
- [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md) — R&D evaluation; item #3.
- [`chimera/engines/reflection.py`](../../chimera/engines/reflection.py) — the call site.
