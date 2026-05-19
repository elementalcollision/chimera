# ADR 0032 — Named-rung selection + skill-assembly journal + dashboard (v4.9)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0031](0031-multi-witness-critique.md)

## Context

v4.8 wired cross-witness critique but the witness pool was limited to
tier-name routing (`("sonnet", "opus")`). Per-rung selection — "use
GPT-5-pro specifically, not the cheapest opus rung" — wasn't possible.

Also, the per-attempt telemetry (`witnesses`, `winning_witness`,
`revised_score`) lived only on the runtime `LadderResult` returned to
the CLI. The mutation table stored a one-line reason string; the
dashboard saw nothing else.

## Decision

### Named-rung selection

`chimera.providers.tiers.resolve_rung(name)` accepts:

- **Tier name** (`"haiku"` / `"sonnet"` / `"opus"`) → that tier's
  cheapest rung (matches `select_rung`).
- **Per-rung alias** (`"gpt-5-pro"`, `"gemini-3-pro"`,
  `"deepseek-v4-pro"`, `"claude-opus-4-7"`, …) → the specific rung
  from any ladder. Alias strips the provider prefix from
  `model_id`.
- **Full model id** (`"openai/gpt-5-pro"`) → the same matching rung.
- Unknown name → `ValueError` with the valid-tier + alias hint.

`assemble_skill` and `critique_and_revise` now use `resolve_rung`
instead of `select_rung`. Existing tier-name callers are unchanged;
cross-witness callers can now pass things like
`witnesses=("claude-opus-4-7", "gpt-5-pro", "gemini-3-pro")`.

### Skill-assembly journal

New module `chimera/skills/journal.py`:

- `record_assembly(mutation_id, skill_name, ladder_result)` appends a
  JSONL row to `state/skill_assembly_log.jsonl` with the full
  per-attempt detail: tier, base score, revised score, witnesses,
  winning_witness, failure_reason.
- `list_assemblies(limit=20)` returns the newest-last list.
- `AssemblyJournalEntry` dataclass for typed access.

`chimera skills assemble` now writes one journal row per run
(best-effort; failures swallowed).

### Dashboard

- New `lib/graph.ts` types: `AssemblyAttempt`, `AssemblyJournalEntry`.
- New `readAssemblyJournal(limit)` reader.
- New "Skill assembly attempts" section on the dashboard above "All
  mutations". Per mutation: skill name, recorded timestamp, winning
  tier, final score/ok. Per attempt: tier, base%, revised%,
  witnesses, winner, failure reason.

## Non-goals

- **No persistence of the actual generated code.** Only the
  validation outcomes are journalled. Inspecting the failed handler
  text still requires running `mutations show <id>` or reading the
  api_calls table.
- **No automatic retention.** The JSONL grows monotonically;
  operators rotate it manually.
- **No telemetry aggregation in this ADR.** A future pass can group
  by skill-name / tier / witness and surface "Anthropic OPUS scores
  highest on synthesis tasks" — the raw data is there now.

## Tests

`tests/test_named_rung_and_journal.py` (7 cases):
- `resolve_rung("haiku")` returns the cheapest rung (not the
  Anthropic safety net).
- `resolve_rung("gpt-5-pro")` / `"gemini-3-pro"` /
  `"deepseek-v4-pro"` resolve correctly.
- `resolve_rung("claude-opus-4-7")` and the full
  `"openai/gpt-5-pro"` id both work.
- Unknown name raises with a helpful message.
- Journal round-trips a single entry preserving witnesses + revised
  state.
- Winner case preserves `winning_tier` and `winning_witness`.
- `list_assemblies(limit=)` returns the newest-N entries.

Full suite: 496 passing.
