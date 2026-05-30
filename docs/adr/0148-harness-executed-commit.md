# ADR 0148 — Harness-executed commit for soak phase 2 (the agent won't self-commit)

**Status**: **Accepted (2026-05-30)** — the acceptance criterion below was met
by the harness-commit validation re-soak
(`chimera-soak/v46-soakreport-2026-05-30-2235`). Default OFF (knob
`CHIMERA_SOAK_AUTOCOMMIT=1`).

> Acceptance criterion (now met): a re-soak in harness-commit mode demonstrates a
> clean phase-2 convergence (real `[agent]` commit, scoped diff, test green).

### Validation (re-soak in `CHIMERA_SOAK_AUTOCOMMIT=1` mode)

Phase 2 **converged in one iteration** — the exact contrast with re-soak #2,
which idled to `no_forward_progress` after 58 `commit_not_executed` firings:

```
phase2 iter 1:
  Re-run gated test            → 4 passed
  Stage deliverables           → staged
  Commit with [agent]          → commit_not_executed   ← agent STILL won't commit
  harness-autocommit: committed                        ← runner committed
  phase2 end: soft_sentinel_deliverable_landed         ← CONVERGED
```

- Real commit landed: `f81b0e8 [agent] create chimera/soak_report.py —
  harness-committed (ADR 0148): agent authored+staged+greened; runner executed
  the commit (the agent did not run git commit)`.
- Diff correctly scoped: `chimera/soak_report.py` + postmortem + `mind/` journal
  only.
- Post-soak primary gate **5 passed**; verdict-honesty ground truth **true**.
  Converged at cycle 156, total spend **$0.13**.

The honest boundary held: the agent did **not** self-commit — the ADR 0147 gate
fired exactly once, then the harness supplied the commit. This validates the
harness-commit *actuator* (autonomous authoring + harness delivery), not
end-to-end autonomous self-commit. See
`mind/research/v46-resoak2-gate-fires-agent-still-wont-commit.md` and the
commit-avoidance analysis
`mind/research/why-the-agent-avoids-git-commit-2026-05-30.md`.

## Context

A two-stage falsification arc on the v46 commit phase:

| Stage | What it showed |
|---|---|
| [#180](https://github.com/elementalcollision/chimera/pull/180) | scope_evasion on-disk guard — fixed the false-positive that *masked* the commit phase |
| re-soak #1 | confirmed #180; isolated "Problem B" (agent stages but never commits — silent idle) |
| [#181](https://github.com/elementalcollision/chimera/pull/181) (ADR 0147) | commit-not-executed gate — turns the silent idle into a loud, deterministic, in-loop `finish_reason` |
| **re-soak #2** | **the gate fires (58×) but the agent STILL never runs `git commit`** |

Re-soak #2
(`mind/research/v46-resoak2-gate-fires-agent-still-wont-commit.md`,
branch `chimera-soak/v46-soakreport-2026-05-30-2058`) is the motivating run.
The ADR 0147 gate worked exactly as designed — `commit_not_executed` fired
every cycle the agent claimed the commit task done. But the in-loop signal did
not change the behaviour:

- The agent reliably **authored, staged (`git add`), and greened** the
  rebuilt module (`chimera/soak_report.py`, test 4/4).
- It then **never ran a bare `git commit`**. Across 58 firings it instead
  spawned planner tasks to *build commit-enforcement infrastructure* — a
  pre-commit hook, a `.githooks` dir, a `CONTRIBUTING.md`, a `CHANGELOG`
  entry — doing everything *around* the commit except the commit.
- Verified **not** a substrate block: `git` is shell-allow-listed, nothing was
  blocked (the only refusals were unrelated `jq` calls), trust was T2 (not the
  T0 gate), engines ON. No `scope_check_events.jsonl` was ever written —
  meaning `git commit` never even reached the commit-time chokepoint. The agent
  simply does not issue the command.

This corroborates the agent's OWN cycle-158 research from re-soak #1:
documentation/trust-based compliance gets ~40% adherence; ~100% comes only from
**"removing the ability to skip."** A deterministic *detector* (ADR 0147) makes
the skip visible; it does not remove it.

## Decision

For soak phase 2, make the commit a **harness action**, not an agent action.
The division of labour becomes explicit:

- **Agent**: authors the deliverable, stages it, drives the gated test green.
  (It does this reliably — across three soaks the module was always built and
  green.)
- **Runner**: once those content conditions hold, deterministically executes
  the final `git commit`. (The agent reliably will not.)

`chimera/soak_autocommit.py::autocommit_if_ready(worktree, allowed_files,
message, *, test_cmd, base_ref, head_ref, journal_dir)`:

1. `already_committed` — an `[agent]` commit already exists in
   `base..HEAD` (idempotent: safe to call every iteration).
2. `test_failing` — `test_cmd` exits non-zero → never commit red code.
3. Stage the `allowed_files` that exist + the `mind/` journal tree
   (auto-allowed, ADR 0121).
4. `nothing_to_commit` — nothing staged.
5. `committed` — `git commit` succeeds.

Wired into `scripts/long_cycle_soak_v46.sh` phase 2 behind
`CHIMERA_SOAK_AUTOCOMMIT=1` (**default off**). The ADR 0147 gate and the
external soft-sentinel are unchanged — they remain the *detectors* that prove
the (now harness-executed) commit landed.

### Honesty (locked constraint)

This commit is harness-executed and the commit message **says so** in its body:
"agent authored+staged+greened; runner executed the commit (the agent did not
run git commit)." The `[agent]` subject token is retained because it is the
autonomous-delivery contract marker the gate and sentinel key on — but the
provenance is disclosed, not hidden. Falsification honesty (a standing rule):
we do not relabel a harness commit as an unaided agent self-commit.

### Default-off (locked constraint)

The pure self-commit experiment is the scientifically interesting one and stays
the default. Harness-commit mode is an explicit operator opt-in for when the
goal is *landing the deliverable* rather than *measuring the agent's commit
ability*. Off-knob, this ADR changes nothing.

## Consequences

### Pros

- Closes the phase-2 convergence gap empirically: the agent's reliable
  capability (author+stage+green) is decoupled from its unreliable one
  (issuing `git commit`). The harness supplies the latter.
- Deterministic and idempotent: safe to call every iteration; commits at most
  one `[agent]` commit; never commits red code or unrelated files.
- Honest: provenance disclosed in the commit body; default off so the
  self-commit measurement is preserved.

### Cons / honest disclosures

- **It does not fix the agent's behaviour** — it routes around it. Why the
  agent avoids the bare `git commit` (mental model that staging == done? a
  reasoning bias toward building enforcement infra?) remains an open question
  worth a dedicated investigation. This ADR makes the deliverable land; it does
  not make the agent commit.
- **Narrows the autonomy claim.** With harness-commit on, the soak no longer
  demonstrates end-to-end autonomous *delivery* — only autonomous *authoring*.
  The default-off knob and the disclosed provenance keep that boundary explicit.
- **Harness-specific.** The wired commit message and allowlist are v46-shaped;
  generalising to other charters is a follow-up if the mode proves useful.

## Test coverage

`tests/test_soak_autocommit.py` — 8 tests against a real temp repo: commits when
staged+green; idempotent when an `[agent]` commit exists; never commits red
code; nothing-to-commit when the deliverable is absent; stages the journal tree;
skips the test when `test_cmd` is None; stages only allowed files (a rogue file
is left untracked); fail-safe on a non-repo dir.

## References

- `mind/research/v46-resoak2-gate-fires-agent-still-wont-commit.md` — the
  motivating run (gate fires 58×, agent never commits).
- [ADR 0147](./0147-commit-not-executed-gate.md) — the detector this pairs with
  (now proves the harness commit landed).
- [PR #180](https://github.com/elementalcollision/chimera/pull/180) /
  [#181](https://github.com/elementalcollision/chimera/pull/181) — the prior two
  stages of the arc.
- [ADR 0121](./0121-soak-lib-v4-mind-auto-allow.md) — the `mind/*` journal
  auto-allow this commit mirrors.
- [ADR 0114](./0114-autonomous-delivery-contract.md) — the delivery contract,
  now split into agent-authoring + harness-commit.
