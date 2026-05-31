# ADR 0151 — Suppress proposals in a commit-only phase (mechanism C)

**Status**: **Accepted (2026-05-31)** — validated by the forced-stall A/B below.

> Acceptance criterion (now met): a commit-stress soak shows no
> governance-busywork proposals spawned while a commit is pending.

### Validation — forced-stall A/B

Two soaks, identical except for R5, each with the commit made unsatisfiable
(`CHIMERA_SOAK_FORCE_STALL=1`) so phase 2 idles under a genuine prolonged stall —
the condition mechanism C needs. The contrast is unambiguous:

| Arm | R5 (`SUPPRESS_PROPOSALS`) | phase-2 cycles | spend | `src:planner` busywork tasks |
|---|---|---|---|---|
| A (control) | **off** (`0`) | 32 (budget-capped) | $1.56 | **63** |
| B (treatment) | **on** (default) | 150 (budget-capped) | $0.75 | **0** |

- **Control (R5 off):** the planner fired 8 proposal-adding PLAN cycles and the
  agent ran **63** governance-busywork ACT tasks — "Add a CHANGELOG entry",
  "capture action items as discrete tasks", and four variants of "Push the
  commit to the remote" (the planner even hallucinating a commit to push while
  the real commit was force-blocked). Mechanism C, vividly.
- **Treatment (R5 on):** every one of 150 stall cycles logged `PLAN: skipped
  (proposals suppressed — commit-only phase)`; **zero** busywork.

This proves R5 matters under a real stall and rules out H2 (variance): the
difference is deterministic and large (63 vs 0). It also surfaced a **cost**
finding — the control burned **2× the budget in 1/5 the cycles** (proposal/engine
model calls are expensive), so R5 sharply reduces spend during a stall too.

The A/B uncovered and fixed a harness bug: phase 1's `unset
CHIMERA_SUPPRESS_PROPOSALS` clobbered the operator override, so the first control
attempt silently ran suppressed. The runner now captures the operator value at
startup (`OPERATOR_SUPPRESS_PROPOSALS`) and reads that in phase 2. Capstone:
`mind/research/r5-forced-stall-ab-mechanism-c-proven.md`.

## Context

The v46 commit-avoidance analysis
(`mind/research/why-the-agent-avoids-git-commit-2026-05-30.md`) named four
stacking mechanisms behind the agent's failure to self-commit. R4 (the atomic
`git_commit` tool, ADR 0150) dissolved A/B/D and the self-commit re-soak #4
converged on the first iteration — so **mechanism C never got to fire there.**
But C is real and was vivid in re-soak #2: with the commit stuck, the discovery
/ curiosity / reflection engines (and the every-Nth Opus planner) filled the
void with *governance busywork* — "create a git pre-commit hook", "add a
`.githooks` dir", "document the convention in CONTRIBUTING.md", "draft a
CHANGELOG entry" — concrete, safe, "helpful" tasks that out-competed the bare
commit imperative for the agent's attention.

C is a tail risk: it bites when the commit does NOT land on the first iteration
(a slower model, a transient gate refusal, a retry). This ADR closes it so a
non-first-iteration commit phase can't be derailed by proposal spam.

The obvious lever — `CHIMERA_ENGINES_ENABLED=0` — is unusable here: it ALSO
blocks `git commit` at the shell chokepoint (the phase-1 investigation-only
gate, ADR/v4.12). A commit-only phase needs engines-the-env-flag ON (commits
allowed) but engines-the-proposal-source OFF. Those two concerns were conflated
under one flag.

## Decision

Add a distinct knob `CHIMERA_SUPPRESS_PROPOSALS` (default OFF). When set,
`_phase_plan` skips ALL proposal generation — both the every-Nth Opus planner
and the daily Discovery/Curiosity/Reflection engines — and returns early,
exactly like the engines-disabled path, but **without** touching
`CHIMERA_ENGINES_ENABLED`. The loop still runs ACT on the operator INBOX, so the
commit task executes; nothing new can be proposed to compete with it.

The v46 runner sets `CHIMERA_SUPPRESS_PROPOSALS=1` for phase 2 (the commit-only
phase, engines-flag ON) and unsets it for phase 1. Off-knob, behavior is
unchanged.

## Consequences

### Pros

- Closes mechanism C: in a commit-only phase the planner/engines cannot spawn
  governance busywork, so even a multi-iteration commit phase stays focused on
  the one deliverable.
- Cleanly separates "commits allowed" (`CHIMERA_ENGINES_ENABLED`) from "generate
  proposals" (`CHIMERA_SUPPRESS_PROPOSALS`) — two concerns that should never
  have shared a flag.
- Tiny and local: one early-return in `_phase_plan`, one helper, default off.

### Cons / honest disclosures

- **Pre-emptive, not yet soak-proven.** R4 already made re-soak #4 converge
  before C could bite, so this hardening is validated by unit test + reasoning,
  not yet by a soak that *would* have spiralled. The acceptance criterion is a
  commit-stress soak (e.g. a slower commit tier) showing zero busywork
  proposals while a commit is pending.
- **Scope.** It suppresses *all* proposals for the phase — correct for a
  commit-only phase, but it is a blunt instrument that should only ever be set
  during such a phase, never for a general working cycle.

## Test coverage

`tests/test_loop.py` (+2): `CHIMERA_SUPPRESS_PROPOSALS=1` with
`CHIMERA_ENGINES_ENABLED` unset (engines-flag ON) skips PLAN
("proposals suppressed — commit-only phase"), records 0 `proposals_added`, and
makes no model calls; plus the `_proposals_suppressed()` env-parsing unit
(default off; "0"/off vs "1"/"true").

## References

- `mind/research/why-the-agent-avoids-git-commit-2026-05-30.md` — mechanism C.
- `mind/research/v46-resoak4-genuine-self-commit-via-git-commit-tool.md` — R4
  result; C left as the logged follow-up this ADR closes.
- [ADR 0150](./0150-atomic-git-commit-tool.md) — R4, attacks A/B/D.
- [ADR 0148](./0148-harness-executed-commit.md) — the standing fallback.
