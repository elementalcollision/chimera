# ADR 0158 — Real-repo verification gate (B1: the production-value primitive)

**Status**: Accepted (2026-05-31). Tier-B Chip 1 from the
robustness-to-production roadmap.

## Context

Everything Chimera builds so far is verified against a PRE-WRITTEN charter test:
"passes the test we gave it." The teeth gate makes that test trustworthy, and
the loop builds to it — a closed, self-consistent world. Production value (B1) is
the harder, open thing: a change verified against the repo's OWN checks — its
real test suite, its linter, its parse/type checks — none of which were written
for this change. "Makes the codebase better," not "passes the test we gave it."

That requires a deterministic primitive: run the project's real verification over
a worktree and return a structured pass/fail with the failure detail an agent (or
operator) can act on. This is the gate every B-tier capability (fix a real flaky
test, bump a dep, refactor) will iterate against.

## Decision

`chimera/core/repo_verify.py::verify_change(repo_root, …)`:

- Runs the repo's real checks — by default `ruff check` then `pytest` (narrowable
  to the changed files / affected tests via `ruff_paths` / `test_target` to keep
  it cheap).
- Each check is a `(name, argv)` pair, so the orchestration is injectable: unit
  tests use trivial commands (`true`/`false`); the integration test exercises the
  real `uv run ruff check`.
- Returns a `VerificationReport` (`ok`, `failed`, `summary()`) of `CheckResult`s
  (`name`, `passed`, `detail`, `returncode`). A failing check's `detail` is the
  tail of its stdout+stderr — the actionable error text.
- Charter: never raises. A check that times out or whose program is missing is a
  FAILED check with its reason as the detail, not an exception — so the gate is
  safe to run on arbitrary agent output.

## Consequences

### Pros

- The foundational B-tier primitive: a deterministic, structured verdict on a
  change against the *real* pipeline. Same role `verify_test_teeth` (ADR 0152)
  played for the self-charter world, now for the production world.
- Injectable checks make it fully unit-testable AND able to run the real linter/
  suite — the integration test proves the default pipeline invokes the project's
  actual ruff.
- The structured failure detail is what an agent needs to *iterate* against real
  signal (the next chip), not just a pass/fail bit.

### Cons / honest disclosures

- **This is the gate, not yet the loop.** It verifies a change; it does not yet
  drive an agent to *make* and *fix* a change against real failures. That is the
  next chip (a real-task soak that uses this as its gate) — the actual B1
  demonstration.
- **Cost/scope.** Running the full suite is expensive; callers should narrow to
  affected tests/files. Type-checking is not wired by default (ruff + pytest
  only) — a follow-up if the repo adopts a type checker in CI.
- **No change isolation here.** It verifies whatever state `repo_root` is in; the
  caller (a soak worktree) owns producing the change.

## Test coverage

`tests/test_repo_verify.py` (9): all-pass → ok; one-fail → not ok + `failed`
lists it; empty checks → not ok; failure detail captures real stderr; a missing
program is a failed check (not a raise); `default_checks` is ruff-then-pytest and
narrows to targets; report `ok`/`failed` math; and an **integration** test
running the real `uv run ruff check` on a known-clean file.

## Amendment (Chip 2, 2026-05-31) — `chimera verify` verb

The gate is now a first-class command: `chimera verify [--test T] [--ruff P …]
[--timeout S]` runs `verify_change` over the current tree, prints the
`summary()`, writes each failed check's actionable detail to stderr, and exits 0
(all pass) / 1 (any fail). This is the single affordance both the **agent** (run
the real pipeline mid-build and read the failure) and a **B-tier soak** (use as
its convergence criterion) invoke — the bridge from the gate (Chip 1) to the
loop (Chip 3). `tests/test_cli_verify.py` (5): exit-0 on pass, exit-1 + detail
on fail, `--test`/`--ruff`/`--timeout` forwarding, runs against cwd, and an
**integration** test driving the real `uv run ruff check` through the verb.

Honest wrinkle: an *un-narrowed* `chimera verify` currently reports FAIL because
`chimera/cli.py` carries pre-existing lint debt (14 ruff findings; CI runs
pytest only, so main stays green). This is exactly why callers must narrow
`--ruff` to the changed files — the gate reports the repo's true state, debt
included.

## Amendment (Chip 3, 2026-05-31) — the real-task loop

The gate and the verb are now wired into a **loop**: `scripts/real_task_soak.sh`
drives Chimera to make + fix a genuine maintenance change against `chimera
verify`, NOT a pre-written charter test. It is `charter_build_soak.sh`'s sibling
— same two-phase scaffold (phase 1 fix / engines-off / no-commit; phase 2
commit-only / engines-on), same falsification gates, same manual-handoff (NO
auto-push/PR/merge) — with two real-task-specific changes:

- **The gate is the repo's own checks.** Parameterized by `TASK_GOAL`,
  `TASK_FILES` (the in-scope allowlist + ruff scope), and optional `TASK_TEST`,
  it builds `uv run chimera verify --ruff <each file> [--test <target>]` and
  uses *that* as the convergence criterion. The agent iterates against the real
  pipeline's actual failure text.
- **Phase 1 has no `.md` marker.** The deliverable is a modification to existing
  files, so the marker-based phase-1 sentinel doesn't apply. New
  `soak_phase1_verify_green` (soak_lib.sh v5) exits phase 1 purely empirically:
  a real, **in-scope** working-tree diff (mind/* auto-allowed, ADR 0121) AND a
  green gate.

Tests: `tests/test_real_task_soak.py` (4, dryrun) pins the verify-gate
construction, full-suite fallback, autocommit default/override, required-param
guard; `tests/test_soak_phase1_verify.py` (6) pins the sentinel's AND over a tmp
git repo — in-scope+green → landed; no-change → not; red gate → not; out-of-
scope → not; mind/* auto-allowed; bad args → 2.

### What this chip is and isn't

This is the **harness** — the deterministic, tested machinery that *would* drive
a real-task fix to a reviewable commit. It is **not** a live demonstration: no
real soak has been launched (that is a separate, explicit operator action, and a
real task + budget must be chosen). The honest claim is "the loop is built and
its convergence logic is unit-proven," not "Chimera has autonomously fixed a
real bug." That live run is the operator's call.

## Next

- **Operator-run B1 demonstration:** pick a genuine low-risk task (a real
  failing test, a dep bump), set `TASK_GOAL`/`TASK_FILES`/`TASK_TEST`, launch
  `real_task_soak.sh`, and human-review the resulting PR — the first
  literally-production-valuable autonomous output.
- Type-check as a third default check if/when adopted; per-change test selection.

## References

- `mind/research/robustness-to-production-roadmap-2026-05-31.md` — B1.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — the analogous
  deterministic gate for the self-charter world.
