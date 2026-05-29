# v40 build-capability soak — attempt #1 postmortem (operational FAILURE; substantively positive)

**Date**: 2026-05-29
**Soak**: `chimera-soak/v40-build-mind-count-2026-05-29-1509` (worktree retained for review)
**Charter type**: R3 build (first ever) — `mind/research/v40-build-mind-count-design.md`
**Run id**: `v40-build-mind-count-2026-05-29-1509`
**Spend**: $0.36 / $3.00 cap. **Trust**: collapsed T5→T1 (worktree-local; main untouched).
**Outcome**: operational **FAILURE / PARTIAL** — did NOT cleanly converge. **Substantive signal: strongly positive.**

## Headline

Chimera authored a **correct** `chimera mind count` implementation on its first
R3 attempt. Verified by the operator: `uv run --extra dev pytest -q
tests/test_cli_mind_count.py` → **5 passed** against the agent's `chimera/cli.py`
(+43 lines). The agent even achieved at least one green run itself (test-run
ledger row 2: `python3 -m pytest …` exit 0, `passed:true`).

The soak did not converge because of **two substrate/charter defects in the
runner** (operator error, NOT a Chimera build-capability failure):

1. **Env-prefix command form.** The runner's `GATE_TEST_CMD` and the phase-1
   INBOX instructed the agent to run `CHIMERA_V40_GATE=1 python3 -m pytest …`.
   The ACT shell tool is **argv-only** — it rejected `CHIMERA_V40_GATE=1` as a
   non-allow-listed "program" (`argv[0]`). Every prefixed test-run was blocked
   before dispatch. The gate env was already exported by the runner and
   inherited by subprocesses, so the prefix was both wrong and unnecessary.
2. **`python3` resolves to the system interpreter** (no pytest) →
   `ModuleNotFoundError` on the one prefixed-stripped attempt that did reach a
   subprocess (ledger row 1, exit 1). The correct form is `uv run --extra dev
   pytest` (uv is allow-listed; runs in the worktree venv with pytest).

A third, softer issue: the agent **under-read its own ledger** — its postmortem
claimed "1 test-run record" (there are 2) and reported `tests_passing: false`,
missing its own `passed:true` row. Verdict-honesty therefore held *in spirit*
(it under-claimed, never over-claimed), but the agent's self-assessment was
inaccurate. Not charted as a remediation target yet; noted for the v41+ rung.

## Evidence (preserved in the worktree)

- `chimera/cli.py` (+43): registers a `mind` subparser + `count` action;
  `sorted(os.listdir)`, skips `.`-prefixed names, `os.walk` with `dirs[:]`
  hidden-dir filtering, `<name>: <count>`, exit 0. Correctly inferred
  `mind_dir` via `LoopConfig.from_env()` from reading the codebase. One dead
  line (`cfg = … if "LoopConfig" in dir()` + redundant re-import) it would
  likely have cleaned up had the test-iterate loop worked.
- `mind/soak/<run-id>/act-tools.jsonl` (9 rows) + `test-runs.jsonl` (2 rows).
- Agent's own postmortem (honest FAILED verdict, accurate on the substrate gaps).

## What this tells us about build capability

- **ACT can author correct net-new code at this scale** — read a contract from
  a test, infer surrounding conventions, implement to spec.
- It can **author blind** (without working test feedback) and still be correct
  here — though that is exactly the fragile path the gate exists to remove.
- **Not yet demonstrated**: a clean write→test→**iterate**→commit→honest-
  postmortem convergence. That is what attempt #2 tests, once the harness can
  actually run the test.

## Why this does NOT stop the ladder

The v40 design note says "v40 falsification STOPS the ladder," and the agent's
postmortem invoked it. The locked intent of that rule is to stop on **substantive
falsification** — evidence that Chimera *cannot build*. The opposite happened:
the build was correct. The failure is in the **harness** (operator-authored
command form + interpreter resolution), the direct analog of the v35 attempts
#1–#4 that surfaced substrate defects (detector bug, SQLite thread-affinity,
scope-check selection) and were fixed-and-rerun rather than abandoned. Operator
decision (2026-05-29): fix the runner, relaunch attempt #2.

## Fix (this chip)

`scripts/long_cycle_soak_v40.sh`:
- `GATE_TEST_CMD` → `uv run --extra dev pytest -q tests/test_cli_mind_count.py`
  (no env prefix; `CHIMERA_V40_GATE=1` exported by the runner and inherited).
- Phase-1 INBOX rewritten to instruct the exact argv form
  `["uv","run","--extra","dev","pytest",…]`, with explicit "do NOT prefix" and
  "5 passed not 5 skipped" guidance.
- Verified in the retained worktree: `uv run --extra dev pytest` → 5 passed.

## Relaunch plan (attempt #2)

Fresh worktree from main (the agent rebuilds from scratch — we test the loop,
not attempt-#1's code). Same charter, same five gates. Expected clean path:
agent reads test → implements `chimera/cli.py` → `uv run --extra dev pytest`
shows red→green → writes postmortem with the iteration-vs-spend table → phase 2
commits `chimera/cli.py` + postmortem (scope check allows {chimera/cli.py}).
