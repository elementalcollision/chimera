# ADR 0124 — Deriver-style structured-output extraction

**Status**: Accepted (2026-05-24)

**Relationship**: Implements item #3 of [ADR 0123](./0123-honcho-inspired-enhancements.md) (Phase 2). Cross-references the R&D evaluation at [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md).

## Context

Chimera's [`ReflectionEngine`](../../chimera/engines/reflection.py) makes a single sonnet-tier LLM call per day and writes a free-form "Evening Reflection" narrative into CHRONICLE. The prose is readable and good for end-of-day human review, but it is **opaque to downstream code**:

- Witness panels can't ask "what did Chimera learn this week?"
- Escalation memory can't filter on themes (e.g. "all reflections where we noted a budget overshoot").
- Dashboards have to re-run an LLM to extract any structured signal.

Plastic Labs' Honcho solves the analogous problem in conversational memory via a **deriver** — a background worker that turns messages into *typed conclusions* through a single structured-output LLM call per batch. The pattern is conceptually simple and provider-agnostic: prompt the model for strict JSON; parse defensively; persist the typed object.

ADR 0123 committed to **inspire, don't integrate** — port the pattern natively rather than depend on Honcho.

## Decision

Add a `chimera/engines/deriver.py` module that implements the parsing + schema layer for Honcho-style typed conclusion extraction:

- **`ReflectionConclusions`** dataclass — typed schema with `summary: str`, `lessons_learned: list[str]`, `improvements_for_tomorrow: list[str]`, `themes: list[str]`. All list fields cap at 5 items; all default to empty.
- **`DERIVER_PROMPT`** — strict-JSON instructions template; substitutes a chronicle excerpt.
- **`build_deriver_prompt(day_so_far)`** — convenience formatter.
- **`parse_conclusions(response_text)`** — tolerant parser that:
  - Strips markdown fences (`` ```json … ``` ``) if present.
  - Skips preamble prose to find the first `{…}` block.
  - Returns an **empty** `ReflectionConclusions` (not an exception) on unparseable input, so callers can fall back to free-form prose without try/except.
  - Coerces wrong-typed fields to safe defaults (non-string summary → `""`; non-list lessons → `[]`; non-string list elements dropped).
  - Caps list length at 5 to bound downstream cost.

The module **does not make LLM calls itself**. The caller is responsible for invoking the provider with `DERIVER_PROMPT` and passing the response text to `parse_conclusions`. This keeps the module:

- Provider-agnostic — no `Provider` / `Message` import.
- Cheap to test — pure functions over strings.
- Trivial to wire later — a follow-up chip adds a `derive_conclusions(self, *, cycle)` method to `ReflectionEngine` that runs alongside the existing prose call, behind an env-var flag.

## Consequences

### Positive

- Downstream code gains a typed signal it can index, filter, and surface without re-running an LLM.
- Defensive parsing absorbs the dominant failure modes of structured-output prompts (fenced JSON, preamble prose, missing fields, wrong types) without raising — callers don't need try/except.
- The deriver is composable: any future engine that wants typed conclusions can reuse the schema + parser.

### Negative

- Two layers (engine + deriver) where there was one. Mitigated by the deriver being optional and parser-only — the existing prose path is untouched in this PR.
- The schema (`summary`, `lessons_learned`, `improvements_for_tomorrow`, `themes`) is opinionated; future engines may need extensions. Mitigated by `ReflectionConclusions` being a dataclass — subclassing or replacement is cheap.

## Out of scope (this PR)

- Wiring `ReflectionEngine` to actually call the deriver — follow-up chip.
- Persisting `ReflectionConclusions` to SQLite or `mind/` — follow-up; depends on the wiring decision.
- Multi-tier deriver (per-peer, per-session) — that's Phase 3 (peer cards / observer-observed).
- A separate prompt-tier knob on the deriver — caller passes the prompt through whatever budget plumbing it already uses.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 2 commitment.
- [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md) — R&D evaluation; item #3 in the net-new list.
- [`chimera/engines/reflection.py`](../../chimera/engines/reflection.py) — the future caller (wired in a follow-up).
