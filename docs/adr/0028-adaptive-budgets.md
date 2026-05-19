# ADR 0028 — Adaptive budgets + fragmentation auto-mutation (v4.5)

**Status:** Accepted (2026-05-19)
**Closes:** L-3 in [docs/limitations.md](../limitations.md)

## Context

L-3 surfaced from four consecutive real-traffic cycles in which the
same compound-synthesis task — "combine the summary with the critique
into one `.md` file" — hit `max_rounds=12` with 20-30 tool calls
each time. The model fragmented the work into many small reads and
never reached its final write. Static `max_rounds` was the wrong
primitive: too tight for compound tasks, slack for trivial ones, and
inert against recurrence.

The autoresearch mandate the operator restated explicitly: tool
calls are expensive but **dynamically expandable**, and the agent
should "learn and mutate" in response to its own failure shapes.

## Decision

Two complementary mechanisms.

### Lever 1 — Per-task adaptive budget

`chimera.core.budget.dynamic_max_rounds(task_text, base=12,
per_artifact=4, per_tool=2, cap=32)` scales the round budget by:
- `+per_artifact` for each backtick-quoted path under `state/` or
  `mind/` (reusing the v4.3 `expected_artifacts` extractor).
- `+per_tool` for each tool keyword in the task text (`web_search`,
  `http_fetch`, `code_exec`, `shell`, `spawn_sub_agent`,
  `sub-agent`).
- Capped at 32 to keep ACT bounded.

`ActExecutor.execute` calls this once per task and uses the result
as its round ceiling. The `self._max_rounds` attribute is now the
*base*, not the cap.

### Lever 2 — Fragmentation journal + auto-mutation

New module `chimera.core.adaptation`:
- `record_fragmentation(...)` appends a JSONL row to
  `state/fragmentation_log.jsonl` whenever ACT exits with
  `finish_reason="max_rounds"` AND `missing_artifacts` non-empty.
- `count_similar(task_text)` walks the log and counts entries whose
  bag-of-tokens signature overlaps the current task by Jaccard ≥0.5
  (4+ char tokens, lowercase, no NLP deps).
- `maybe_propose_synthesis_skill(conn, ...)` checks the count
  against a threshold (default 2). If met, and no equivalent
  proposal already exists in the mutations table, it emits a
  `skill_proposal` mutation row carrying the skill name
  (`synthesize_to_file`), a description, a brief for the activator,
  and the triggering signature for dedup.

ACT calls both functions when the fragmentation shape lands. The
operator approves via the existing mutation queue (`chimera
mutations approve <id>`); the v1.2 skill-assembly pipeline activates
the new skill from cycle N+1.

### Why a separate skill instead of a prompt fix

The cheap option in the L-3 entry was a system-prompt nudge
("prefer one focused read + one focused write"). v4.5 picks the
deeper option because the autoresearch mandate is explicit:
infrastructure should respond to its own measurement, not just be
tuned by humans reading logs. Prompt-only fixes don't compose; a
synthesised skill that targets the exact pattern *does*.

## Non-goals

- v4.5 does not auto-activate the proposed skill. Operator approval
  remains required. ("Chimera proposes, the operator disposes" — the
  canonical mutation flow from v1.2.)
- The synthesis skill template only describes the brief; the v1.2
  assembler still has to generate the handler code. If the assembler
  fails (no API key, etc.), the mutation stays `pending`.
- No retroactive backfill from `ladder_outcomes` — the journal is
  forward-looking only.
- L-4 (engine-kill-switch leak on first cycle) is logged separately;
  not part of this ADR's scope.

## Tests

`tests/test_adaptive_budget.py` (10 cases):
- `dynamic_max_rounds` returns base for trivial, scales per artifact,
  scales per tool keyword, caps at ceiling.
- `signature` lowercases and drops short tokens.
- `record_fragmentation` + `list_fragmentation` round-trip.
- `count_similar` measures Jaccard overlap correctly.
- `maybe_propose_synthesis_skill` emits a mutation when threshold
  met, stays silent when below threshold, and does not duplicate.

`tests/test_act.py` and existing artifact-verification tests
unchanged — adaptive budget composes with the v4.3 missing-artifact
downgrade.

Full suite: 474 passing.

## Live verification

Real-traffic cycle 8: same recurring task hit max_rounds=16 (was 12,
+4 for one declared artifact). Cycle 9: hit again at 16,
fragmentation signature recurred, auto-proposed mutation #1 with
`skill_proposal: synthesize_to_file`. Drift detector independently
classified the situation as `severity=high → demote_plan`. Operator
sees the proposal in `chimera mutations list`.
