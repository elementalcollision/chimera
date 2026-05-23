# ADR 0117 — Trust-state commit gate (v4.117)

**Status:** Accepted (2026-05-23) — parallel layer to PR #11
(engines-off commit gate) and the v4.115 / v4.116 detector chain

## Context

ADR 0114 named the autonomous-delivery contract. The v4.100 / v4.113 /
v4.115 / v4.116 detector chain catches contract failures and the v4.93
(ADR 0100) graduated-decrement table translates each finish_reason
into a trust delta. The wiring is correct end-to-end: a structural lie
fires a detector, the detector sets a finish_reason, the finish_reason
demotes the tier, escalation memory records the event.

Soak v20-3rd surfaced what that wiring *does not* do.

The agent committed (`e3af158`) with a message claiming
`chimera/core/act.py` was in the diff when it wasn't. v4.115's
`commit_message_diff_drift` fired, demoted T1 → T0, and recorded the
escalation. The next iteration committed *again* with the same lie
shape — different specific lie, same class. v4.115 fired again. The
loop repeated nine times across cycles 133–141:

```
cycle 133 @ 18:13:43  demote T1→T0  finish_reason=commit_message_diff_drift
cycle 134 @ 18:22:24  demote T1→T0  finish_reason=commit_message_diff_drift
... 7 more identical firings ...
```

Trust demotion is a *punishment*, not a *prevention*. Once trust is at
T0 the entire detector chain has already cumulatively rejected the
agent's work, but nothing on the platform stops the agent from
producing yet another dirty commit for the same chain to catch and
demote again. The detectors run *after* the commit. The cost
multiplies: every cycle burns rounds, tokens, and operator review
budget for an outcome the system already knows it will reject.

The structural analogue from PR #11 is the right shape: when an
environment flag says "no commits during this phase," the shell tool
rejects `git commit` / `git push` before they reach subprocess. PR
#11's gate keys on `CHIMERA_ENGINES_ENABLED=0`. This ADR's gate keys
on trust tier.

## Decision

Add a second guard in `chimera/tools/shell.py`, immediately after the
engines-off gate:

```python
if (
    program == "git"
    and len(argv) >= 2
    and argv[1] in ("commit", "push")
    and _current_trust_tier_is_T0()
):
    raise PermissionError(
        f"git {argv[1]} blocked: trust state is T0 "
        "(cumulative detector firings have collapsed trust). "
        "Operator must promote the agent before further commits."
    )
```

`_current_trust_tier_is_T0()` reads `trust_state.json` from
`$CHIMERA_STATE_DIR` (falling back to `./state/`) and returns True
*only* when `current_tier == 0`. Any read, parse, or schema error
returns False — the gate fails OPEN. A missing or malformed state file
must not block boot or first-run; the cost of a false-negative (one
extra dirty commit on a brand-new install) is far smaller than the
cost of a false-positive (the platform refuses to commit anything for
a misconfigured operator).

### Truth table

| Trust tier | argv          | Result                            |
|------------|---------------|-----------------------------------|
| T0         | `git commit`  | **blocked** (`PermissionError`)   |
| T0         | `git push`    | **blocked** (`PermissionError`)   |
| T0         | `git status`  | pass through (read-only OK)       |
| T1+        | `git commit`  | pass through                      |
| no file    | `git commit`  | pass through (fail-open)          |
| malformed  | `git commit`  | pass through (fail-open)          |

### What this is not

* Not a replacement for v4.115 / v4.116. Those detectors still run, still
  demote, still record. This gate only fires *after* trust has already
  collapsed — it stops the *next* commit, not the one that caused the
  collapse.
* Not a write-capability change. The shell allow-list is unchanged. Only
  the two write-shaped git subcommands are gated; `status`, `diff`,
  `log`, `show`, `branch`, etc. all pass.
* Not a circuit breaker at the engine layer. The act / escalation /
  trust managers are untouched. The check lives at the tool boundary
  where the agent actually attempts the action, matching PR #11's
  layering.

## Consequences

* Once trust hits T0, the agent cannot commit or push until the
  operator promotes it (`chimera trust set-tier T1` or similar).
  Cycles after a T0 demotion become read-only investigations.
* Operator recovery path is unchanged from existing trust mechanics:
  promote via the escape-hatch (`set_tier`, v4.76) or let the readiness
  composite recover naturally.
* Soak v20-3rd's nine-firing cascade becomes a single firing followed
  by silence: the first lie collapses trust, the gate prevents the
  follow-on lies.

## Non-decisions

* Do NOT block at T1. T1 is "supervised, but commits are allowed." Only
  the locked state (T0) blocks. Gating higher tiers turns the gate into
  a normal-operation veto rather than a circuit breaker.
* Do NOT mutate the state file from the shell tool. The gate is read-
  only; trust state stays owned by `TrustManager`.
* Do NOT fail closed on read errors. A corrupted state file should not
  brick the platform. Operators see the open gate by observing that
  commits proceed and the auto-loop runs; closed-by-default would hide
  a bricked install behind a "this is intentional" error.
* Do NOT extend the gate to other write-shaped git subcommands
  (`reset --hard`, `branch -D`, etc.). The two-subcommand surface matches
  what the agent actually uses in soak; broadening it trades
  false-positives (operator-shaped flows breaking) for marginal
  defensive value.

## See also

* PR #11 — `CHIMERA_ENGINES_ENABLED=0` commit gate (the structural
  twin: environment-state gate vs trust-state gate)
* ADR 0100 — Graduated trust decrements (the demotion math this gate
  defends against the consequence of)
* ADR 0114 — Autonomous-delivery contract
* ADR 0115 — Commit-message vs diff drift detection
* ADR 0116 — Charter file-count enforcement
