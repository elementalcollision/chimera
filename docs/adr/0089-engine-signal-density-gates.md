# ADR 0089 — Engine signal-density gates (v4.70)

**Status:** Accepted (2026-05-20)

## Context

`mind/postmortems/engine-telemetry-2026-05-20.md` §2 documented:

> The scheduler is doing two things that interact poorly:
> 1. Time-window selection — `pick_due()` picks an engine based on
>    UTC hour. The intent is "discovery at morning, curiosity at
>    midday, reflection at evening."
> 2. Per-day idempotency — each engine fires at most once per UTC
>    day. The intent is to prevent expensive repeated firings.
>
> In an operator-session model (short bursts, often at irregular
> hours), the time-window gating contributes nothing — the operator's
> session covers whatever UTC slice happens to be active. The
> idempotency does the actual work of "fire once per day," which
> could be implemented without any time-of-day logic.

The post-mortem also named the canonical worst-case:

> The 2026-05-19 *evening reflection* from CHRONICLE captured this
> gap explicitly:
>
>   > The midday investigation became meta: I studied the fact that
>   > there was nothing yet to study.

Curiosity fired on 2026-05-19 even though Morning Discovery had
just written "no prior history; fresh session initiation." The
engine had no signal-density check.

This ADR ships **P2** — signal-density gates that sit on top of
the scheduler's existing time-window logic. The scheduler still
picks an engine by UTC hour; the gate decides whether that engine
has anything substantive to act on.

## Decision

### New module `chimera/core/engine_gates.py`

Three pure-function gates returning `GateDecision(allow, reason)`:

| Gate | Source signal | Threshold (default) | Env knob |
|---|---|---|---|
| `discovery_gate(db, cycle)` | `api_calls` in last 5 cycles | ≥ 5 | `CHIMERA_DISCOVERY_MIN_API_CALLS` |
| `curiosity_gate(chronicle_text)` | today's Morning Discovery section | ≥ 2 bullets AND no cold-start marker | `CHIMERA_CURIOSITY_REQUIRE_DISCOVERY` (boolean) |
| `reflection_gate(db, cycle)` | distinct cycles today with api_calls | ≥ 3 | `CHIMERA_REFLECTION_MIN_CYCLES` |

Master switch: `CHIMERA_ENGINE_GATES_ENABLED=1` (default ON). Set
to 0 to revert to the pre-v4.70 "fire whenever the scheduler says
so" behaviour.

Each per-engine threshold also supports a `0` value to disable
that gate individually while keeping the others.

### Cold-start markers for curiosity

`curiosity_gate` rejects when the Morning Discovery body matches
any of:

- `"no prior history"`
- `"fresh session initiation"`
- `"earliest stage of activity"`
- `"session is at earliest"`

These are the exact phrases the DiscoveryEngine itself wrote on
cold-start days (per the 2026-05-19 chronicle). The post-mortem
named this as the biggest behavioural fix — investigating "there's
nothing yet to investigate" is the canonical anti-pattern.

### Engine integration

Each engine's `run()` consults its gate *after* the provider check,
*before* any model call. When the gate refuses, the engine writes
a `status="skipped"` engine_runs row with the gate reason and
returns `EngineResult(skipped=True)`. Visible to the operator as
"engine X declined to fire because Y" rather than a silent no-op.

```python
gate = discovery_gate(self._db, cycle=cycle)
if not gate.allow:
    finish_engine_run(
        self._db, run_id, status="skipped", skip_reason=gate.reason,
    )
    return EngineResult(skipped=True, failure_reason=gate.reason, …)
```

For CuriosityEngine: the gate runs *before* allocating the
`q{NNN}` question directory. This prevents the proliferation of
`mind/wiki/projects/q001-fresh-session/` and
`mind/wiki/projects/q002-fresh-session/` directories that the
2026-05-19 cold-start produced.

### Scheduler interaction

The scheduler's time-window logic stays unchanged. The gate is a
*second* filter on top: scheduler picks the engine of the hour,
then the engine checks its own gate. If the gate denies, the
engine's `mark_ran` in the scheduler is *not* called (because the
engine returned `EngineResult.skipped=True`), so the same engine
gets another chance next cycle. This matches the operator
intuition of "the agent waited because nothing was happening."

## Tests

`tests/test_engine_gates.py` — 20 new tests:

- Master switch (default on, env-off path)
- `discovery_gate`: empty DB skips, threshold met allows, env
  override, threshold=0 disables, master switch
- `curiosity_gate`: no chronicle, no today section, no Discovery
  section, cold-start marker, single bullet, substantive (≥2)
  allows, master switch, prereq disable
- `reflection_gate`: quiet day skips, threshold met allows,
  threshold=0 disables, master switch
- 2026-05-19 burn regression — replays the exact cold-start
  chronicle text and proves the gate would skip

Full suite after v4.70: 767 passing (was 747, +20 new).

## Non-goals

- **No removal of scheduler time-window logic.** Pre-v4.70
  operators rely on it; the gate sits on top. A future ADR can
  retire the scheduler's UTC routing if data shows the gates
  carry all the weight.
- **No automatic threshold tuning.** Defaults are
  postmortem-derived best guesses. Operators tune via env. A
  future ADR can add learned thresholds based on the
  `engine_runs.status` history (skipped vs success ratio).
- **No new `should_fire` method on the base class.** Engines call
  their gate function directly — simpler than an abstract method
  for a per-engine logic shape. Refactor opportunity if a fourth
  engine ever lands.
- **No reflection-gate check on the chronicle.** Reflection's
  signal is api_calls count, not chronicle content. The chronicle-
  as-input loop is part of P5, deferred until the acceptance-rate
  scoring (P3) is in place.

## Why this shape

Why thresholds at 5 / 2-bullets / 3? Because those are the
postmortem-observed inflection points. The 2026-05-19 session had
exactly 4 api_calls when curiosity fired (below 5); the Morning
Discovery had 3 cold-start bullets (would still pass a ≥2 bullets
count check — which is why the cold-start marker check is
necessary in addition to the count). Conservative defaults that
match the canonical bad day.

Why pure functions instead of a base-class method? Because each
gate has a different shape — discovery looks at the DB, curiosity
looks at the chronicle file, reflection looks at the DB but with
a date filter. A unified `should_fire(...)` interface would
either be overly abstract or leak per-engine concerns into the
base class. Pure functions per engine are easier to read and to
unit-test.

Why default ON (and the master switch to recover the old
behaviour)? Because the post-mortem's data was clear: the engines
fire less usefully than they could, and the cold-start
investigation is a documented anti-pattern. Default ON makes the
correct behaviour the default. Operators who genuinely want
unconditional firings (e.g. for testing or for a specific
research session) flip the switch.

Why does the curiosity gate take `chronicle_text` directly
instead of a `ChronicleManager`? Because passing the text makes
the gate unit-testable without an in-process chronicle manager.
The engine reads its chronicle file path and passes the contents
— that's the only I/O coupling we need.
