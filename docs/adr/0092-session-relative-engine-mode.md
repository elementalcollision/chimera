# ADR 0092 — Session-relative engine routing + code_exec cwd fix (v4.74)

**Status:** Accepted (2026-05-20)

## Context

The 2026-05-20 long-cycle multi-agent test
(`mind/long_cycle_test_plan_2026-05-20.md`) opened at 19:33 UTC — well
past Discovery's window (08:00–13:59) and inside Reflection's
(22:00–07:59). Over 91 iterations of the runner, Curiosity tried to
fire **54 times** and was correctly rejected every time by the v4.70
signal-density gate with `"today has no Morning Discovery section"`:

> The gate is doing exactly what ADR 0089 said it would — but the
> canonical operator session shape (yours) hits the edge case the
> post-mortem itself flagged.

The Reggio engines (`Discovery → Curiosity → Reflection`) were
designed around a 24-hour rhythm: distil the morning, explore at
midday, reflect at evening. That model assumes the agent is *always
running*. For an operator-attended Chimera that fires up for a few
hours of ad-hoc work and shuts down, the UTC-window scheduler routes
every session into a single engine — whichever happens to own the
operator's local timezone slice — and the other two never fire.

Separately, the same run surfaced a path-doubling bug:
`mind/mind/research/*.md` files appeared because `code_exec.py`'s
`_resolve_cwd` joined relative cwd arguments onto `roots[0]` (the
resolved absolute mind directory), producing `mind/mind/...` when a
model passed `cwd="mind"`. The `shell.py` tool was fixed for the
same issue in v4.4 (L-2); `code_exec.py` never got the same
treatment.

## Decision

### Part 1 — Session-relative engine routing

A new opt-in mode for `EngineScheduler.pick_due` that replaces the
UTC-window check with a session-relative dedup key. Default OFF —
the v1.1 daily-rhythm behaviour is preserved unless the operator
opts in.

| Env | Default | Meaning |
|---|---|---|
| `CHIMERA_ENGINE_SESSION_MODE` | `0` | When `1`, engines fire by priority order rather than UTC window, deduped per session |

When session mode is on AND the loop passes a `session_id` (it does —
`self._state.session_started_at`):

1. Time-of-day check **bypassed**.
2. Engines tried in priority order: `discovery → curiosity → reflection`.
3. Each engine that's per-engine-enabled and hasn't fired this
   session becomes eligible.
4. First eligible engine is returned; the loop calls `engine.run()`,
   v4.70's signal-density gate still applies on top.
5. On success, `mark_ran` stores the session_id under
   `"session:<engine>"` so the next cycle skips it.

When session mode is off (default), UTC-window logic is unchanged.

`mark_ran` writes **both** the date-keyed value (existing v1.1
behaviour) and — when session mode is on — a session-keyed shadow
entry. This means the operator can flip the env on and off without
losing either dedup history.

### Part 2 — `code_exec` cwd L-2 port

`chimera/tools/code_exec.py` now mirrors `shell.py`'s `_allowed_roots`
+ `_default_cwd` pattern from v4.4:

- `_allowed_roots()` returns `[mind, state, shared_parent?]` — the
  parent of mind+state is appended when they share one (the
  typical layout).
- `_default_cwd()` picks `roots[2]` when present, else `roots[0]`.
- `_resolve_cwd(cwd_arg)` joins relative paths onto `_default_cwd()`
  rather than `roots[0]`, so `cwd="mind"` resolves to mind/, not
  mind/mind/.

Two regression tests assert the file lands at `mind/research/*` and
the `mind/mind/` directory is never created.

## Tests

`tests/test_engine_selective_enable.py` — 8 new session-mode tests:

- Evening-PDT scenario: UTC mode picks reflection at 23:00, session
  mode picks discovery (priority head). Reproduces the long-cycle
  burn directly.
- Three-cycle rotation: discovery → curiosity → reflection → None.
- New session resets dedup.
- Per-engine disable still applies in session mode.
- Session mode OFF uses UTC window (backward compat).
- Session mode ON with no session_id falls back to UTC (defensive).
- Global kill (`CHIMERA_ENGINES_ENABLED=0`) still wins over session mode.
- `mark_ran` stores both date and session keys.

`tests/test_code_exec.py` — 2 new regression tests + 2 amended:

- `test_code_exec_cwd_mind_does_not_double_prefix` — exact long-cycle
  reproduction.
- `test_code_exec_cwd_state_does_not_double_prefix` — symmetric.
- `test_code_exec_can_write_to_mind` amended to pass explicit
  `cwd="mind"` (default cwd changed from mind → repo root).
- `test_code_exec_rejects_cwd_outside_roots` amended to use a path
  truly outside the parent (the parent is now an allowed root).

Full suite: 791 passing (was 781, +10 new minus 0 lost).

## Non-goals

- **Not changing the default.** Operators running Chimera as a
  daemon (24/7) want the daily rhythm. The default stays UTC mode;
  ad-hoc operators opt in. A future ADR can flip the default once
  enough operator data confirms session mode is the common case.
- **No automatic detection of "operator session vs daemon."** That
  would require heuristics on cycle cadence, presence of
  `session_started_at`, etc. Out of scope — the env flag is the
  clean operator switch.
- **No dashboard surface for session-mode state.** The session-keyed
  dedup is visible via `scheduler.snapshot()` for anyone who wants
  to render it; the control plane mirror is a follow-up.
- **No retroactive backfill of `mind/mind/` paths in the
  filesystem.** Already cleaned up manually for the 2026-05-20 run;
  future runs use the fixed `_resolve_cwd`.

## Why this shape

Why opt-in rather than smart auto-detection? Because the post-mortem
context flagged this as a *design tension*, not a bug. The Reggio
rhythm is a real design — daemons benefit from it, operators don't.
A single env flag lets the operator declare which mode they want
without Chimera guessing wrong.

Why priority order (discovery → curiosity → reflection)? Because
the engines have an information dependency: Curiosity reads
Morning Discovery to derive seed topics (v4.70 gate enforces this);
Reflection reads both. Firing them in this order during a session
maximises the chance each has its prerequisites met.

Why store both date and session keys in the same dict? Because
they're orthogonal dedups. Flipping the env shouldn't erase the
operator's history of which engines fired today (UTC) or this
session. Two namespaces, one file, no migration.

Why couple the code_exec cwd fix into this ADR rather than a
separate one? Because they came out of the same long-cycle run as a
single class of "session-shape lessons": one is about *when* an
engine fires, the other about *where* a tool writes. Both ride a
post-2026-05-20 review of the run's surprises.
