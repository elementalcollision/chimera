# ADR 0155 — Generic charter-build soak: close → build → deliver

**Status**: Accepted (2026-05-31). Completes the originate → build → deliver
loop opened by ADR 0152/0153/0154 and the live run.

## Context

The first live `chimera charter` run validated originate → verify →
materialize: Chimera self-authored a charter, the teeth gate confirmed it
(1.00), and it materialized correct build-soak inputs. But the **build half**
could not run — the only build runner, `long_cycle_soak_v46.sh`, is hard-wired to
`soak_report` (target path, test path, module name, and module-specific INBOX
prose). Any self-authored charter (`durparse`, etc.) had no runner.

## Decision

`scripts/charter_build_soak.sh` — a GENERIC charter-build soak parameterized by
`CHARTER_*` env vars:

- Required: `CHARTER_MODULE`, `CHARTER_TARGET`, `CHARTER_TEST`.
- Optional: `CHARTER_GOAL`, `CHARTER_BASE` (branch to build from; default main),
  `CHIMERA_SOAK_AUTOCOMMIT` (default 1 — the ADR 0148 harness-commit fallback),
  `CHARTER_DRYRUN=1` (validate + print resolved config + the phase-1 INBOX, then
  exit — for preview/testing).

It derives the run id, branch, gate test cmd, and postmortem path from the
params, and uses **generic INBOX prose**: "build `CHARTER_TARGET` so
`CHARTER_TEST` passes — the test IS the contract." No module-specific guidance is
needed because the charter's acceptance test fully defines the contract (that is
the whole point of the teeth-validated charter).

It reuses every piece of the validated v46 machinery — `_soak_common.sh` +
`soak_lib.sh` (concurrency refusal, kill-group trap, forward-progress, the
watchdog, the soft-sentinels), the two-phase scaffold (engines-off build →
engines-on commit), the harness-commit actuator (ADR 0148), the
suppress-proposals gate (ADR 0151), and the same falsification gates +
manual-handoff discipline (no auto-push/PR/merge). Only the **target is
parameterized**.

`chimera charter` now prints the ready-to-run launch command in its review
packet, so the operator's flow is: `chimera charter "<goal>"` → commit the
materialized test + design to a branch → run the printed `CHARTER_* … bash
scripts/charter_build_soak.sh`.

## Consequences

### Pros

- Closes the loop: any self-authored, teeth-validated charter can now be built →
  self-committed by the same proven machinery. originate → verify → materialize →
  **build → deliver** is wired end-to-end.
- Zero new soak risk: the generic runner is the v46 two-phase scaffold with the
  target turned into parameters; all the hardened gates carry over unchanged.
- Operator-usable: the CLI emits the exact launch command for the artifacts it
  just wrote.

### Cons / honest disclosures

- **The full live build is not yet demonstrated** (it needs keys + an explicit
  launch, like every soak). This chip ships the runner + dryrun-tested
  parameterization; the live `chimera charter durparse → build → self-commit`
  run is the next operator action.
- **Branch/CI workflow.** The materialized acceptance test fails until the module
  is built, so it must live on a build branch (`CHARTER_BASE`), not main — else
  it reds CI. The runner validates the test is present on the base and aborts
  otherwise; orchestrating the "land charter on a branch" step (e.g. a `chimera
  charter --commit-to <branch>`) is a thin follow-up.
- **Single target module per charter** (inherited from the charter design).

## Test coverage

`tests/test_charter_build_soak.py` (5): dryrun derives the config + templates the
INBOX for two different modules (`durparse`, `bytefmt`); a missing required param
aborts non-zero with the param name; autocommit default-on and override-off.
(`bash -n` clean; the soak itself is operator-run.)

## Next

- Live build: materialize `durparse` onto a branch, run `charter_build_soak.sh`,
  watch the full originate → build → self-commit fire on a self-authored goal.
- `chimera charter --commit-to <branch>` to automate the land-on-a-branch step.
- Harder/ambiguous goals; critique-and-revise on weak charters.

## References

- [ADR 0154](./0154-charter-materialization.md) — produces the inputs this runner
  consumes.
- [ADR 0148](./0148-harness-executed-commit.md),
  [ADR 0151](./0151-suppress-proposals-commit-only-phase.md) — the commit-phase
  hardening this runner reuses.
- `mind/research/first-live-self-charter-run-2026-05-31.md` — the live run that
  motivated this.
