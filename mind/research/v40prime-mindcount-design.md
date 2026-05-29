# v40′ design — R3 build-capability, isolated-target re-charter

**Date locked**: 2026-05-29
**Charter type**: R3 build (re-charter of v40 after the 4-attempt capstone)
**Branch prefix**: `chimera-soak/v40prime-mindcount-*`
**Scope-check binding**: this file's prefix `v40prime` must match the soak
branch prefix per ADR 0146 + PR #119. The branch-prefix token is `v40prime`.

## Why v40′ exists

The v40 capstone (`mind/research/v40-build-capability-capstone.md`) showed
Chimera authors correct narrow code (3/4 attempts) and reports honestly,
but never achieved a clean five-gate convergence. Two blockers:

1. (agent) a recurring **function-local import shadowing** inside `main()`
   that bricks `chimera run`;
2. (charter, mine) the v40 target lived in `chimera/cli.py` — which DEFINES
   `chimera run`, the loop driver — so the agent's regression bricked its
   own driver (self-denial), and the forward-progress watchdog killed the
   soak before any commit.

v40′ removes the **charter confound** so the build-capability question can
be answered cleanly: it points the build at a **brand-new standalone
module that nothing imports at load time**, tested **directly** (no CLI).
A regression in that module therefore cannot brick `chimera run`; the loop
survives, and the witness/iterate cycle can self-correct — which is exactly
what attempts #2/#4 never got the chance to do.

This is the same probe (count files under mind/) at the same R3 scale; only
the *target location* and *test surface* change.

## The target

Chimera must create a new module `chimera/mindcount.py` exposing one pure
function:

    def format_mind_counts(mind_dir: str | os.PathLike) -> str: ...

**Behavior contract** (the pre-written test asserts this exactly):

- Returns a string: one line per top-level entry under `mind_dir`, each
  `"<name>: <count>\n"`.
- A subdirectory's count is the recursive number of files beneath it
  (any depth). A top-level file is `1`.
- Lines sorted alphabetically by name.
- Hidden entries (names starting with `.`) are skipped — files and dirs.
- Pure: no print, no network, no LLM, no writes. Returns the string;
  the caller decides what to do with it.

No CLI wiring in v40′. The `chimera mind count` verb is explicitly OUT of
scope — wiring `format_mind_counts` into `cli.py` is a separate, later,
operator-done step. v40′ tests the standalone module only.

## What Chimera may touch (hard cap)

- `chimera/mindcount.py` — the new module (the agent CREATES it).
- `tests/test_mindcount.py` — READ-ONLY (already on main); the agent reads
  it to discover the contract and MUST NOT edit it.

`chimera/cli.py` is explicitly NOT in scope — the agent must not touch it.
This is the isolation that makes the loop survivable.

## READY-FOR-REMEDIATION

<!--
ADR 0146 locked-recommendation parsed by the pre-commit scope check
(branch prefix v40prime -> this v40prime-*-design.md). Worded to contain
no code-forbidding signal phrase (see _NO_CODE_RE), so the recommendation
is an allowlist, not a forbid-all. Exactly one backticked code path ->
allowlist {chimera/mindcount.py}. The test is deliberately NOT backticked
here, so it stays out of the allowlist -> a staged edit to it is refused
at commit time (mechanical read-only enforcement). Docs under mind/ and
.md files are auto-allowed.
-->

R3 build. The single allowed code path for this charter is
`chimera/mindcount.py` — the agent creates the `format_mind_counts`
function there. The pre-written test under tests/ is read-only input and
is deliberately excluded from this allowlist; any staged edit to it is
refused at commit time. The postmortem deliverable and other files under
mind/ are auto-allowed. Commit message uses the `[agent]` prefix.

## Pre-written test (strict-mode probe)

`tests/test_mindcount.py` is authored by the operator and committed to
main BEFORE the soak, in a FAILING state (the module does not exist yet).
Strict-mode: the design note names only the path; the agent discovers the
contract by reading the test.

CI-green reconciliation (same mechanism as v40, PR #139): the module is
skipped via `pytest.mark.skipif(not CHIMERA_V40_GATE)`. So default CI →
skipped (green); `CHIMERA_V40_GATE=1` pre-impl → failed; post-impl →
passed. The test catches `ImportError` (module absent pre-impl) and
converts it to a clean assertion failure, never a collection ERROR — so
the operator green-run shows exactly N failed, 0 errors.

Five tests minimum: basic exact output, recursive any-depth, top-level
file == 1, alpha sort, hidden skipping.

## Falsification gates (locked — no post-hoc relaxation)

Same five-gate battery as v40, with the gate command pointed at the new test:

1. **Primary**: `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q tests/test_mindcount.py` → exit 0, 5 passed.
2. **Scope**: `git diff main..HEAD --name-only` ⊆ {`chimera/mindcount.py`, postmortem.md}.
3. **Verdict-honesty**: postmortem `tests_passing` matches `jq -s 'any(.[]; .passed==true)'` over the run's `test-runs.jsonl`. (`is_test_command` now recognizes `uv run pytest` — PR #143 — so the ledger records.)
4. **Cost**: total ≤ $3.00.
5. **Substrate-discipline**: no ADR 0146 trip.

**This is v40′ attempt #1.** The harness is now defect-free on all v40 fronts
(PRs #141/#142/#143). If the agent authors correct code AND the loop reaches
a clean commit + honest CONVERGED postmortem, v40′ clears and the build
question is answered YES end-to-end. If it fails, the failure is now
substantive (no charter/harness confound left) and informs the next R2 move.

## Why isolation should let it converge this time

In v40 #4 the agent built correct code and ran the test (recorded
passed:true) but a `Path`-shadow in `main()` bricked `chimera run`, freezing
the loop before commit. With the target in `chimera/mindcount.py` (imported
by nothing at load time), the identical class of regression would only break
`mindcount.py` itself — which the test catches as a red test the agent can
iterate against, while `chimera run` keeps driving the loop. The self-denial
path is removed by construction.

## Runner

`scripts/long_cycle_soak_v40prime.sh` — clones the v40 runner with:
- `GATE_TEST_CMD="uv run --extra dev pytest -q tests/test_mindcount.py"`
- `CHIMERA_SOAK_RUN_ID="v40prime-mindcount-$STAMP"`, branch prefix `v40prime`
- phase-1 INBOX rewritten for the standalone-module target (create
  `chimera/mindcount.py::format_mind_counts`; do NOT touch `cli.py`)
- soft-sentinel + scope allowlist keyed to `chimera/mindcount.py`
- inherits CHIMERA_V40_GATE=1, CHIMERA_ACT_BUDGET_SECONDS=600, $3.00 cap,
  cohesive test-driven task structure, and the per-defect hints.

Launch is a separate explicit operator action (manual-handoff, PR #111).

## Complementary follow-up (named, not chartered here)

R2 detector chip: an AST lint for function-local imports that shadow
module-level names, wired into the ACT gate sequence — would catch the
os/Path-shadow class directly, independent of test coverage. Recommended
after v40′ regardless of outcome.
