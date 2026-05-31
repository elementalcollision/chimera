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

## Next

- **B1 loop:** a real-task soak — give Chimera a genuine low-risk maintenance
  task (a real failing test, a dep bump), let it iterate against `verify_change`
  (real ruff + pytest) rather than a pre-written charter test, human-review the
  PR. The first literally-production-valuable output.
- Type-check as a third default check if/when adopted; per-change test selection.

## References

- `mind/research/robustness-to-production-roadmap-2026-05-31.md` — B1.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — the analogous
  deterministic gate for the self-charter world.
