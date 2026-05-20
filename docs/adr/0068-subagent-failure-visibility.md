# ADR 0068 — Sub-agent failure visibility (v4.49)

**Status:** Accepted (2026-05-19)

## Context

The Agonistic Futures cycle 1 had the model spawn a sub-agent with
model id `gpt-5-pro` (which doesn't exist on OpenRouter). The
sub-agent's ACT executor hit `provider_error`, then `provider_unavailable`,
returned an `ActResult(completed=False)` with no `final_text`, and
the runner serialised that as:

```
(sub-agent finished without text; finish_reason=provider_error)
```

— and returned it as a **successful** tool result. The parent model
saw a benign string and could not tell delegation had silently
failed. Worse: there was no signal to escalate tier on the parent's
next round, because v4.46 only records failures in the *parent* ACT,
not in nested sub-agent ACTs.

## Decision

New `SubAgentFailed(Exception)` in `chimera/tools/subagent.py`.
`SubAgentRunner.run` now raises it whenever `result.completed is
False`, carrying:

- `finish_reason` — same enum as ActResult (max_rounds, provider_error, …)
- `failure_reason` — the human-readable detail string
- `tier`, `rounds_used`, `api_call_count`
- `final_text` — whatever the sub-agent did emit before bailing

The exception's `__str__` is a one-line concise summary the parent
model can pattern-match against:

```
sub-agent FAILED on tier='haiku'; finish_reason=max_rounds; rounds=4; api_calls=5; last_text='I tried...'
```

The dispatcher's existing generic-exception path then converts this
into an `is_error=True` ToolResultBlock — so the parent model sees a
clear failure in the next round, can decide to retry with a
different tier, change strategy, or give up. The v4.41 schema-hint
appendix also kicks in because dispatch errors trigger that path.

### When success-without-text happens

A sub-agent CAN legitimately complete with no final text (rare: it
returned via `stop` after writing artifacts and not producing prose).
That case still returns a benign string — "(sub-agent completed
without final text)" — as a success. Only `completed=False` raises.

## Tests

`tests/test_subagent.py` — 2 new tests:

- `test_sub_agent_failure_raises_structured_error` — exhausting
  rounds in the inner provider raises `SubAgentFailed` with
  finish_reason='max_rounds' and the expected tier/rounds fields.
- `test_sub_agent_failure_propagates_through_dispatcher` — going
  through `Dispatcher.dispatch("spawn_sub_agent", …)` propagates the
  exception (which ACT's `_run_one` then converts to is_error).

Full suite: **569 passing**, 5 skipped.

## Non-goals

- **Recording sub-agent failures into v4.46's task_escalations.**
  The sub-agent's brief is usually distinct from the parent task; we
  don't want to pollute the parent's escalation memory with sub-
  agent-specific signatures. A future ADR could add a separate
  `subagent_escalations` table if useful.
- **Auto-retry inside the runner.** Caller decides. The parent model
  is now informed; it can spawn again with a different tier if it
  wants.
