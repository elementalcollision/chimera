# ADR 0094 — Operator-first ASSESS priority + INBOX task provenance (v4.78)

**Status:** Accepted (2026-05-20)

## Context

During the 2026-05-20 v2 long-cycle interventional soak test the operator
authored a 7-item phase-1 inbox to investigate the `degenerate_loop_abort`
bug. After 5 of 7 tasks completed, v4.74's session-relative engine routing
let all three engines (Discovery / Curiosity / Reflection) fire in the
same session. The engines wrote chronicle entries — and the Opus planner,
fed by the fresh chronicle, started appending follow-on tasks to
`mind/INBOX.md`:

> - Audit tool invocation success rates and latency trends from cycles 120-139…
> - Compile a retrospective summary of the last 10 cycles…
> - Define a primary objective for this session…
> - Verify operational status of all integrated tools and models…

ASSESS reads `INBOX.md` in file order and has no notion of **task
provenance** — operator bullets and agent-appended bullets are
equivalent. With the agent-proposed rows mixed into the queue, ACT
started executing them instead of finishing the operator's original
work. The last 2 phase-1 tasks (write investigation doc, append
cross-witness critique) were never reached.

This is the same shape as the "agent self-direction beats operator
intent" failure mode the trust system is designed to guard against —
but at the *task-routing* layer rather than the trust layer.

## Decision

1. **Provenance tag on every agent-appended row.**
   `ChimeraLoop._append_proposals_to_inbox()` now stamps each new
   bullet with an inline HTML comment `<!-- src: {source} -->`. Default
   `source="planner"`; engines that grow inbox-write capability later
   pass their own name (`discovery`, `curiosity`, `reflection`).

2. **`InboxTask.source` field + parse-time extraction.**
   `parse_inbox()` searches each task line for `<!-- src: X -->` and
   populates `InboxTask.source`. Lines without the tag get `source=None`
   — interpreted as **operator-authored**.

3. **ASSESS sorts operator-first.** `_phase_assess` stable-sorts open
   tasks by `(t.source is not None)` so all operator rows precede all
   agent-proposed rows. File order is preserved within each group.
   ASSESS telemetry now reports `operator_tasks` and `agent_tasks`
   counts.

## Backward compatibility

Pre-v4.78 inbox rows have no `src:` tag and parse with `source=None` —
treated as operator-authored and sorted to the front. No migration
needed; existing inboxes continue to work as before.

## Non-goals

- **Per-cycle quota** on agent-proposed appends. Discussed and
  deferred. The provenance tag is the prerequisite; a quota is one
  `if` away once a soak run shows inbox bloat is still a problem.
- **UI surfacing.** The HTML comment is invisible in rendered markdown
  but visible in raw view — sufficient for now. Pretty-printing
  `[planner]` / `[discovery]` chips on the dashboard is a v4.x+ nicety.
- **Engine inbox-writing.** Today only the Opus planner appends to
  INBOX. The provenance machinery is ready for engines if/when they
  gain that path.

## Consequences

- The operator's authority over agent self-direction is now formalised
  at the routing layer: an idle cycle's Opus planner cannot preempt
  in-flight operator work, no matter how many tasks it proposes.
- Combined with ADR 0093 (artifact validation) and ADR 0092 (session
  routing), the long-cycle soak failure mode that prompted this work
  is fully addressed: engines fire in-session, generate substrate,
  planner proposes follow-ons, but the operator's queue runs first.

## Files touched

- `chimera/core/mind.py` — `_INBOX_SRC_RE`, `InboxTask.source`, parse.
- `chimera/core/loop.py` — `_append_proposals_to_inbox(..., source=)`,
  `_phase_assess` sort + telemetry.
- `tests/test_assess_priority.py` — 5 new tests covering parse,
  backward-compat, sort, planner-tag round-trip, engine-source round-trip.
