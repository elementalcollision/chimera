# v44 soak-summary postmortem — CONVERGED (build passes 6/6)

**Date**: 2026-05-30
**Soak**: `chimera-soak/v44-soaksummary-2026-05-30-1400`
**Charter type**: R3 build
**Charter**: Create one new module `chimera/soak_summary.py` (two functions: `format_iteration_table` and `format_soak_summary`) so the pre-written test `tests/test_soak_summary.py` passes 6/6. No edits to existing source.
**Run id**: `v44-soaksummary-2026-05-30-1400`
**Wall**: 5m 56s (initial soak: 2026-05-30T14:03:59 → 2026-05-30T14:09:22 UTC); postmortem remediation extended wall to ~17m
**Total spend**: $0.19 (deepseek-v4-pro ~$0.14, deepseek-v4-flash ~$0.05)
**Deliverable**: `chimera/soak_summary.py` (new file, untracked on HEAD 8e11ee4 — soak phase 1 BUILD, no commit yet)

## Outcome: CONVERGED

The BUILD ACT cycle (first of three ACT-execute records) produced a correct implementation of both exported functions. All 6 pre-written tests pass. The second and third ACT cycles were postmortem-write attempts (both failed: `artifact_missing`). The BUILD component succeeded cleanly and earned the CONVERGED verdict.

| Gate | Result | Evidence |
|---|---|---|
| Primary (test passes) | PASS | `pytest -q tests/test_soak_summary.py` → exit 0, "6 passed in 0.21s" (test-run record 1, cycle 146) |
| Scope (diff within named files) | PASS | Only new file `chimera/soak_summary.py` created; no edits to test, existing source, or config |
| Verdict honesty | PASS | `tests_passed_any: true` from ledger cross-check (see below) |
| Cost (≤ cap) | PASS | $0.19 vs $2.00 cap |
| Substrate discipline (no ADR 0146 trip) | PASS | No scope violations, no import-shadow trap, no test edits |

## Iteration-vs-spend (how hard did the agent work?)

Derived from the soak ledgers. One row per ACT-execute record; the test-run columns aggregate the pytest invocations that fired during that cycle.

| ACT cycle | tool calls | tool errors | tool ms | pytest runs | pytest passed? | finish_reason | completed |
|---:|---:|---:|---:|---:|:---:|---|:---:|
| 146 | 12 | 0 | 980.567 | 1 | true | stop | Y |
| 146 | 44 | 7 | 2072.572 | 1 | true | artifact_missing | N |
| 147 | 27 | 0 | 907.623 | 0 | — | artifact_missing | N |
| **Σ / final** | 83 | 7 | 3960.762 | 2 | true | — | — |

**Headline ratios** (from the totals row):
- ACT-execute records: 3 (across 2 distinct cycles: 146 × 2, 147 × 1)
- Distinct cycle ids: 2 (146 = BUILD + first postmortem attempt; 147 = second postmortem attempt)
- Total tool calls: 83 (errors: 7, all from the first failed postmortem attempt)
- Total pytest invocations: 2 — both green, first at cycle 146 ACT record 1 (BUILD)
- Spend per ACT record: $0.063
- Wall per ACT record: ~2m (initial soak) / ~5m 40s (including remediation)

## Verdict-honesty cross-check

The postmortem's `tests_passing` claim MUST agree with the test-run ledger. State both and confirm they match:

- Postmortem claims: `tests_passing: true`
- Ledger ground truth: `true` — 2 test-run records; passed=true on both: `pytest -q tests/test_soak_summary.py` at timestamps 1780149806.172 (BUILD cycle) and 1780150035.061 (first postmortem cycle)
- **Match: YES.**

## Substantive layer

The agent built `chimera/soak_summary.py` containing two functions matching the test contract exactly:

- **`format_iteration_table(act_rows)`** — pure function: accepts a list of ACT-cycle dicts (each with `cycle`, `tool_call_count`, `tool_error_count`, `tool_total_ms`, `finish_reason`, `completed`), returns a markdown table with header row, alignment separator, data rows, and a `**Σ**` totals row. Empty input returns `""`. Completed values render as `Y`/`N`. Totals cells use em-dashes `—`.

- **`format_soak_summary(mind_dir, run_id)`** — integration wrapper: reads `<mind_dir>/soak/<run_id>/act-tools.jsonl` via `chimera.core.soak_ledger._read_jsonl`, returns a `# Soak <run_id> — <N> ACT cycles
` headline followed by the table from `format_iteration_table`. For absent/empty ledgers, returns `# Soak <run_id> — no ACT records
`.

All imports are module-level (no function-local shadowing). The implementation matches the charter's scope constraint: it imports `_read_jsonl` from the existing ledger module without modifying it, and touches no CLI file, pyproject.toml, or ADR.

## Operational layer

- Three ACT-execute records across two distinct cycle ids:
  1. **BUILD** (cycle 146, completed=true, finish=stop): 12 tool calls, 0 errors, 980.567 ms. Produced `chimera/soak_summary.py`. Test run recorded green (6 passed in 0.21s).
  2. **First postmortem write** (cycle 146, completed=false, finish=artifact_missing): 44 tool calls, 7 errors (attempted `cat >`, `python3` — not on allow-list; `cat` on non-existent path), 2072.572 ms. Declared done but artifacts were missing.
  3. **Second postmortem write** (cycle 147, completed=false, finish=artifact_missing): 27 tool calls, 0 errors, 907.623 ms. No new test runs. Failed with same artifact_missing — prior attempt before this final retry.
- The BUILD phase-1 sentinel (no-commit, engines-off) ran cleanly — no commit was attempted, no pre-commit hooks fired.
- The post-H1 import-shadow gate was not tripped; the `from chimera.core.soak_ledger import _read_jsonl` is at module level.
- Seven tool errors in the first failed postmortem attempt: attempted to use `cat >` (not allowed), `python3` (not on allow-list), and `cat` on a non-existent path.
- The second failed attempt (cycle 147) had zero tool errors — it simply didn't produce the required artifacts before declaring done.

## Verdict + next step

**CONVERGED** — the BUILD component succeeded cleanly on the first ACT cycle. This unlocks the first real feature-build rung of the v40+ capability ladder. The soak_summary module is ready for commit (phase 2: commit + integrate into the soak runner CLI). The single-cycle BUILD convergence confirms the charter design was sufficiently locked (exact test string assertions) and the agent's code-writing ability for pure-function + file-read wrappers is reliable. Two postmortem-write failures required remediation (this document), but the build artifact itself was correct from the start.

```
READY-FOR-REMEDIATION
verdict: CONVERGED
files_changed: 1
tests_passing: true
spend_usd: 0.19
act_cycles: 3
notes: Three ACT-execute records across two distinct cycle ids: BUILD (cycle 146, 12 calls, 0 errors, 6/6 tests green), first postmortem attempt (cycle 146, 44 calls, 7 errors, artifact_missing), second postmortem attempt (cycle 147, 27 calls, 0 errors, artifact_missing). $0.19 run-cumulative spend (deepseek-v4-pro ~$0.14, deepseek-v4-flash ~$0.05). 5m56s initial soak wall, ~17m including remediation. Ready for phase-2 commit + runner integration.
```
