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

## Amendment (W2 fix, 2026-05-31) — real-task soak writes its own scope note

The first **live** real-task soak (injected fault: `islower`→`isupper` in
`chimera/strcase.py`) produced a correct, minimal, scope-clean fix and a
gate-green commit — but via the *fallback* path, and surfaced a real runner gap:

**W2 — the agent's own commit was refused, not the agent's fault.** The ADR-0146
pre-commit scope check binds to the newest `*-design.md` by mtime. The
real-task soak wrote **no** scope note, so the check bound to a *stale*
`v46-soakreport-design.md` left in the worktree (allowlist
`chimera/soak_report.py`) and refused the staged `chimera/strcase.py` as
out-of-scope. The agent (3 rounds, 32s) hit `commit_not_executed`; only the
ADR-0148 harness-autocommit fallback got the work in, masking the block.

**Fix.** `real_task_soak.sh` now writes
`mind/research/realtask-<runid>-design.md` with a `## READY-FOR-REMEDIATION`
allowlist == `TASK_FILES`, at setup (newest by mtime → the note the check binds
to). Verified: this flips `check_commit_scope` from *refuse* to *allow* for an
in-scope change. `tests/test_real_task_scope_note.py` (4) runs the runner's
GENERATED note through the REAL `check_commit_scope` — the gate that fired:
in-scope → allow; out-of-scope → refuse; **fresh note wins over a stale
prior-soak note** (the exact W2 condition); multi-file allowlist. This is the
regression that would have caught W2.

Still open from that run (separate follow-ups, NOT addressed here):
- **W1** — phase-1 engines-off has no completion check, so the agent marked the
  fix "done" with sub-10ms no-op tool calls (never ran the gate). The
  verify-green sentinel correctly prevented false convergence (phase 1 ran to
  `no_forward_progress`), but the over-claim + wasted iterations remain.
- **W3** — the runner logged `cycle=`/`spend=` blank (DB telemetry not
  resolving); the forward-progress watchdog tripped on the stall signal.

## Amendment (W1 fix, 2026-05-31) — phase-1 build-completion gate

A second live run with the harness fallback OFF (`CHIMERA_SOAK_AUTOCOMMIT=0`)
falsified the clean story: the agent **never made the fix** — it marked the
"prove `chimera verify` is green" task complete with sub-10ms no-op tool calls
(gate never run, file never edited), phase 2 then looped on `commit_not_executed`
trying to commit a nonexistent change, and nothing landed. Run-to-run variance
(run 1 made the fix; run 2 didn't) showed **W1 is the dominant reliability
blocker, not W2** — the first run only "succeeded" because the harness fallback
silently committed work the agent's own loop didn't reliably produce.

**Fix — `check_verify_claim_invalid` (chimera/core/act.py).** A new in-loop
completion gate, the build-step analogue of `check_test_claim_valid` /
`check_commit_not_executed`: when a task demands a green verification
(`_task_demands_verify_green`) and a verify command is configured
(`CHIMERA_PHASE1_VERIFY_CMD`, set by `real_task_soak.sh`), it **re-runs that
command** and, if red, sets `completed=False` / `finish_reason=
verify_claim_invalid` — so the agent cannot self-report the build done while the
gate is still red; the task stays open and it must actually make it green.
Soak/env-scoped (no-op off-soak or unconfigured) and fail-open on subprocess
error, like its siblings. The command is runner-controlled, never parsed from
agent output. `tests/test_verify_claim_gate.py` (10): demand-detection;
soak/env/task scoping no-ops; fires on red; passes on green; env-var supplies
the command; unrunnable command counts as red. No regression in the 362-test
ACT-gate slice.

W3 (telemetry) still open.

## Next

- **Re-run the B1 demonstration** with the W2 fix and confirm GENUINE agent
  self-commit (an `[agent]` commit from the agent's own `git_commit`, not the
  harness fallback). Then W1/W3.
- **Operator-run B1 demonstration:** pick a genuine low-risk task (a real
  failing test, a dep bump), set `TASK_GOAL`/`TASK_FILES`/`TASK_TEST`, launch
  `real_task_soak.sh`, and human-review the resulting PR — the first
  literally-production-valuable autonomous output.
- Type-check as a third default check if/when adopted; per-change test selection.

## References

- `mind/research/robustness-to-production-roadmap-2026-05-31.md` — B1.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — the analogous
  deterministic gate for the self-charter world.
