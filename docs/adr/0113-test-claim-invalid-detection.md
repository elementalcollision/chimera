# ADR 0113: Test-claim invalid detection (v4.113)

**Status**: Accepted
**Date**: 2026-05-22
**Soak**: v16 (PR #5, merged)

## Context

Across soaks v1–v15 we built up a 14-detector chain that verifies an
agent's task completion against **structural** properties of the
work it shipped:

| Layer | Detector | What it checks |
|---|---|---|
| v4.79/83 | artifact_missing / ungrounded_citation | Files the task named exist; cited symbols appear in their source |
| v4.82 | scope_evasion | Named code paths were actually touched |
| v4.92/99 | fix_without_test (per-task, phase-scope) | chimera/ edits ship with tests/ counterparts |
| v4.96 | artifact_incomplete | Required content markers ("MUST contain", "EXACTLY:") present |
| v4.100 | inbox_claim_invalid | `[x]` checkbox flips correspond to a real deliverable |
| v4.101 | syntax_invalid | py_compile passes on every *.py written |
| v4.102/103/109/110/112 | witness_rejected (panel) | Second-model semantic review of diffs |

In **soak v16** an agent claimed it had implemented an orphan-worktree
health check in `chimera/core/doctor.py` and verified the work with
`uv run pytest tests/test_doctor.py`. The chain cleared every gate:

- `chimera/core/doctor.py` parsed cleanly (syntax_invalid: pass)
- `tests/test_doctor.py` was written and modified (fix_without_test: pass)
- The INBOX checkbox flip pointed at files that existed (inbox_claim_invalid: pass)
- The witness panel read the diff and approved it (witness_rejected: pass)

But the implementation used `re.compile(...)` without importing `re`.
Five of six tests **NameError'd at runtime**. The diff was structurally
correct and the agent's own shell-tool exit code self-reported success;
nothing in the chain ran the code.

This is a systematic gap: **structural-correctness checks are necessary
but not sufficient. Runtime-behavior verification is its own layer.**

## Decision

Add `test_claim_invalid` as the first **runtime-behavior** detector:

1. **ACT-time** (per-task): `check_test_claim_valid(task_text, write_targets, worktree_root)`
   scans `task_text` for explicit pytest claims of the form
   `uv run pytest tests/<path>.py` or `python -m pytest tests/<path>.py`,
   re-runs each named file from an operator-side subprocess, and
   returns the list of files whose exit code is non-zero.
   Wired between `syntax_invalid` (cheap parse gate) and
   `witness_rejected` (expensive semantic gate). Fires
   `finish_reason="test_claim_invalid"`.

2. **Submit-PR gate**: `_validate_tests_actually_pass(worktree, changed_files)`
   re-runs pytest against every modified `tests/test_*.py` in the
   branch diff. Catches the cumulative case where no single task
   tripped the per-task check but the branch ships a broken test.
   Same audit-log shape as the v4.92 / v4.100 / v4.102 gates already
   in `chimera/core/submit_pr.py:validate()`.

3. **Trust delta**: `-1` (one-tier demote). Same severity as
   `fix_without_test` and `syntax_invalid` — incomplete delivery
   against an explicit "tests pass" contract, recoverable from a
   single hint.

4. **Remediation hint**: `_test_claim_invalid_hint` names the failing
   files and pastes the last ~8 lines of pytest output so the model
   sees the actual error rather than a generic prompt. Fix the
   implementation, not the test.

5. **Escalation**: added to `ESCALATING_FINISH_REASONS`. Same
   three-strikes auto-skip path as syntax_invalid / fix_without_test.

## Non-decisions (deliberate)

- **Don't infer.** Only fire on EXPLICIT `uv run pytest <path>` /
  `python -m pytest <path>` mentions in `task_text`. Inferring that
  a task "should have run tests" produces false positives on
  investigation-shaped work.
- **Don't run the full suite.** Per-task and submit-PR gates both
  re-run only the named/modified files. Soak runs already exercise
  the whole suite via the long-cycle runner; this detector is
  scoped to claim-vs-reality.
- **Don't trust the agent's shell-tool exit code.** Operator-side
  subprocess re-run is the ground truth. Soak v16 ran `pytest` via
  the agent's shell tool and the agent reported success despite a
  non-zero exit — that's the failure shape this detector exists
  to close.
- **Don't replace `pytest --collect-only`.** This is about *running*,
  not *collecting*. A clean collection is necessary for any
  runtime check but not sufficient.

## Consequences

**Positive**

- First runtime-behavior detector in the chain. The chain now has
  parse-time, structural, semantic, AND execution layers.
- The soak v16 fixture (NameError-at-runtime regression) is now
  caught at ACT time AND at submit-PR time.
- Hint quality is high: the model sees the actual pytest tail and
  knows exactly which test failed.

**Negative**

- Re-running pytest costs seconds per detector invocation. Mitigated
  by `-x` (stop on first failure) and a 120s timeout. Only fires
  when the task explicitly claims a pytest run, so the marginal
  cost over a soak is small.
- Test-file detection assumes Python projects with `tests/test_*.py`
  naming. Non-standard layouts (`spec/`, `__tests__/`) don't get
  the gate. Acceptable: this is chimera-shaped tooling for
  chimera-shaped projects.

## Future work

v4.114+ may extend the runtime-behavior layer to:

- **Compile-and-import smoke** for non-test *.py writes (catches
  the `re` import case even without a test file naming the module).
- **Property-test fuzz**: when a task names a pure function,
  generate fuzz inputs via Hypothesis and call it.
- **Reproducer extraction**: when an existing failing test cites a
  specific input, re-run only that test rather than the whole file.

## References

- Soak v16 motivating fixture: PR #5 (https://github.com/elementalcollision/chimera/pull/5)
- Failure point: `chimera/core/doctor.py:190 NameError: name 're' is not defined`
- Sibling detectors: ADR 0099 (fix_without_test), ADR 0105 (syntax_invalid), ADR 0106 (witness)
- Trust table: `chimera/trust/manager.py:48 FINISH_REASON_TRUST_DELTAS`
