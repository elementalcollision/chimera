# ADR 0150 — Atomic `git_commit` tool (the path to genuine self-commit)

**Status**: **Accepted (2026-05-31)** — the acceptance criterion was met by the
self-commit re-soak (`chimera-soak/v46-soakreport-2026-05-31-0012`,
`CHIMERA_SOAK_AUTOCOMMIT=0`): the agent self-committed via `git_commit` and phase
2 converged. See the Validation section below.

> Acceptance criterion (now met): a re-soak with `CHIMERA_SOAK_AUTOCOMMIT=0`
> shows the agent self-committing via `git_commit` and phase 2 converging.

### Validation — genuine autonomous self-commit

Phase 2 converged **in one iteration on the agent's own commit**, with the
harness commit OFF:

```
phase2 iter 1:
  Re-run gated test                       → 4 passed
  "Commit … in ONE step with git_commit"  → stop, tools=1, completed=True   (agent called git_commit ONCE)
  phase2 end: soft_sentinel_deliverable_landed                              (CONVERGED)
```

- `harness-autocommit` log count: **0** — the harness did not commit. This was
  the agent.
- Commit: `3141352 [agent] create chimera/soak_report.py`; diff scoped to
  `chimera/soak_report.py` + the postmortem.
- **Zero `commit_not_executed` firings** (re-soak #2 had 58). Post-soak gate
  **5 passed**; verdict-honesty ground truth **true**; converged at cycle 156,
  total spend **$0.14**.

The decisive contrast across the commit-mode re-soaks:

| Re-soak | Commit affordance | Phase-2 outcome |
|---|---|---|
| #2 | bare `git commit` (shell) | 58× `commit_not_executed` → no_forward_progress |
| #3 | harness commits (ADR 0148) | converged — but the harness did it |
| **#4** | **`git_commit` tool, autocommit OFF** | **agent self-committed → converged** |

Same agent, same avoidance of the bare shell `git commit` — but given one
blessed atomic tool it committed on the first call. This is the **first
end-to-end autonomous delivery** (author → stage → green → self-commit) in the
arc, and it confirms the analysis's read of the avoidance as single-shot
under-execution + staging-≈-done + gate-risk-aversion (mechanisms A/B/D), all
dissolved by collapsing the ritual into one affordance. Capstone:
`mind/research/v46-resoak4-genuine-self-commit-via-git-commit-tool.md`.

## Context

The v46 commit-phase arc:

- [#180](https://github.com/elementalcollision/chimera/pull/180) fixed the
  scope_evasion false-positive masking the commit phase.
- [#181](https://github.com/elementalcollision/chimera/pull/181) (ADR 0147)
  added the commit-not-executed *detector* — turned a silent idle into a loud
  in-loop signal.
- [#182](https://github.com/elementalcollision/chimera/pull/182) (ADR 0148)
  added the harness-commit *actuator* — the runner commits when the agent won't.
  Validated: phase 2 converged.
- The analysis `mind/research/why-the-agent-avoids-git-commit-2026-05-30.md`
  established the behaviour: the agent reliably **authors + stages + greens** but
  does not issue a bare `git commit`. Four stacking mechanisms — **(A)** staging
  ≈ done, **(B)** gate-induced risk aversion, **(C)** planner meta-work
  amplification, **(D)** single-shot ACT under-execution.

ADR 0148 routes *around* the agent. This ADR is the complementary move toward
genuine autonomous self-commit, per the analysis's recommended R4.

## Decision

Add an atomic `git_commit` tool (`chimera/tools/git_commit.py`) registered in
`register_core_tools`. One call — `git_commit(message, paths?)` — stages the
named paths and creates ONE commit, returning the new HEAD.

Crucially it **does not bypass any commit gate**: it routes the `git add` and
`git commit` through `chimera.tools.shell.shell_handler`, so the allow-list, the
engines-off block, the T0 trust gate, and the ADR 0146 pre-commit scope check
(plus the H1 index-bypass refusal) ALL fire exactly as for a hand-issued commit.
A gate refusal is returned to the agent as text (not a crash) so it learns the
reason and can correct.

What the tool removes is the agent's ability to *skip* the commit, attacking
three of the four mechanisms:

- **A (staging ≈ done)** — the tool's success IS the commit; there is no
  staged-but-uncommitted intermediate to mistake for completion.
- **B (risk aversion)** — the gated complexity sits behind one blessed
  affordance instead of a free-form shell incantation.
- **D (single-shot under-execution)** — one tool call completes the whole ritual
  (stage → commit → return HEAD), so the agent's one-action-then-stop tendency
  now *lands* the commit rather than stopping at a read.

(**C**, planner meta-work amplification, is not addressed here; a complementary
move is to quiet the engines during the commit-only phase — left to a follow-up.)

The message is auto-prefixed with the `[agent]` marker if absent (friction
removal + contract compliance). The v46 phase-2 INBOX now instructs the agent to
use `git_commit`, so the next re-soak with `CHIMERA_SOAK_AUTOCOMMIT=0` tests
genuine self-commit.

## Consequences

### Pros

- A real path to autonomous *delivery* (not just authoring): if the agent calls
  the one blessed tool, the commit lands — with every existing protection intact.
- Zero new trust surface: all commits still pass the same gates; the tool is a
  thin orchestration over the audited shell path.
- Composes with ADR 0148: harness-commit remains the fallback when even the tool
  isn't invoked.

### Cons / honest disclosures

- **It still requires the agent to CHOOSE to call the tool.** If the avoidance is
  strong enough that the agent won't invoke `git_commit` any more than it ran
  `git commit`, R4 won't help — that is exactly what the next re-soak falsifies.
  This ADR is a *hypothesis with a test*, not a proven fix.
- **Does not address mechanism C** (planner pulling toward meta-work); a quiet-
  engines-in-commit-phase follow-up is the complement.
- The tool is general but its INBOX wiring is v46-shaped; broadening to other
  charters is a follow-up if it proves out.

## Test coverage

`tests/test_git_commit_tool.py` — 9 tests against a real temp repo: stages paths
+ commits + returns HEAD; commits an already-staged index with no `paths`;
`[agent]` auto-prefix (added / preserved); the engines-off gate refusal surfaces
as text with no commit landing; empty-message and bad-paths validation;
registration into a registry and into `register_core_tools`.

## References

- `mind/research/why-the-agent-avoids-git-commit-2026-05-30.md` — the analysis
  that recommended this (R4).
- [ADR 0147](./0147-commit-not-executed-gate.md) — the detector this pairs with.
- [ADR 0148](./0148-harness-executed-commit.md) — the route-around fallback.
- [ADR 0146](./0146-pre-commit-scope-check.md),
  [ADR 0117](./0117-trust-state-commit-gate.md) — the commit gates this tool
  routes through unchanged.
