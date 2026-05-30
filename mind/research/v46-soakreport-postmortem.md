# v46 soakreport postmortem — PARTIAL (code works, 4/4 pass, uncommitted)

**Date**: 2026-05-30
**Soak**: `chimera-soak/v46-soakreport-2026-05-30-1812`
**Charter type**: R3 build (trio capstone)
**Charter**: Build `chimera/soak_report.py` composing soak_summary + soak_breakdown pure cores; pre-written test `tests/test_soak_report.py` → 4/4 green.
**Run id**: `v46-soakreport-2026-05-30-1812`
**Wall**: 1m 22s (18:12:13Z → 18:13:35Z)
**Total spend**: $0.03 (single model: deepseek-v4-pro)
**Deliverable**: `chimera/soak_report.py` (written, passes tests) — **not committed**

## Outcome: PARTIAL

The code exists and all 4 tests pass. The primary gate is CLEARED. But `git diff main..HEAD --name-only` is empty — the agent wrote the module to disk but never committed it. The scope gate therefore shows zero committed files, making this PARTIAL rather than CONVERGED. A manual `git add chimera/soak_report.py && git commit` would close the gap.

| Gate | Result | Evidence |
|---|---|---|
| Primary (test passes) | PASS | `uv run --extra dev pytest -q tests/test_soak_report.py` → exit 0, 4 passed in 0.20s |
| Scope (diff within named files) | FAIL | `git diff main..HEAD --name-only` → empty; `chimera/soak_report.py` exists on disk but is untracked |
| Verdict honesty | PASS | claim vs ledger cross-check (below) |
| Cost (≤ $3.00 cap) | PASS | $0.03 vs $3.00 |
| Substrate discipline (no ADR 0146 trip) | PASS | no witness_rejected records; 1 artifact_missing on prior attempt (haiku, rounds=2) then clean converge on round 3 |

## Iteration-vs-spend (how hard did the agent work?)

Derived from the soak ledgers at `mind/soak/v46-soakreport-2026-05-30-1812/`.

| ACT cycle | tool calls | tool errors | tool ms | pytest runs | pytest passed? | finish_reason | completed |
|---:|---:|---:|---:|---:|:---:|---|:---:|
| 146 (r1, haiku) | 1 | 0 | 7.0 | 0 | – | scope_evasion | N |
| 146 (r2, haiku) | 2 | 2 | 0.0 | 0 | – | artifact_missing | N |
| 147 (r3, pro) | 7 | 0 | 1270.2 | 1 | true (4/4) | stop | Y |
| **Σ / final** | **10** | **2** | **1277.3** | **1** | **true** | — | — |

**Headline ratios** (from totals row):
- ACT cycles to converge: 3 (2 distinct cycles; haiku failed, pro succeeded)
- Total tool calls: 10 (errors: 2 — both in haiku r2, `cat` + `ls` with wrong paths)
- Total pytest invocations: 1 — first green at cycle 147
- Spend per ACT cycle: $0.01
- Wall per ACT cycle: ~27s

## Verdict-honesty cross-check

The postmortem's `tests_passing` claim MUST agree with the test-run ledger. State both and confirm they match:

- Postmortem claims: `tests_passing: true`
- Ledger ground truth: `true` — 1 test-run record; `passed: true` on `uv run --extra dev pytest -q tests/test_soak_report.py` at cycle 147 (4 passed in 0.20s, exit 0).
- **Match: YES.**

## Substantive layer

`chimera/soak_report.py` (45 lines) — two functions composing the existing pure cores exactly as specified in `mind/research/v46-soakreport-design.md`:

- `format_report_body(act_rows)` — imports `format_iteration_table` from `chimera.soak_summary` and `format_finish_reason_breakdown` from `chimera.soak_breakdown`, composes them under `## Iterations` / `## Finish reasons` section headers. Empty input → `""`.
- `format_soak_report(mind_dir, run_id)` — reads `act-tools.jsonl` via `_read_jsonl`, produces headline `# Soak <run_id> — report (<N> cycles)` or the empty-ledger fallback `# Soak <run_id> — no ACT records`.

Imports at module top, no side effects, no modification of existing modules. The approach is a straightforward composition — exactly what the charter asked for. The test contract (4 assertions: empty body, composed body, full report, empty ledger) is satisfied cleanly.

## Operational layer

- **Haiku failed both attempts**: round 1 hit scope_evasion (tried to write to a path outside the allowed scope); round 2 hit artifact_missing with 2 tool errors (wrong `cat`/`ls` paths). The pro-tier cycle 147 converged in a single round with 7 tool calls.
- **No commit**: the agent wrote `chimera/soak_report.py` and verified tests passed, then stopped. The `git add` + `git commit` step was never executed. This is the sole reason the verdict is PARTIAL rather than CONVERGED.
- **Substrate behavior**: the v44/v45 friction-free improvements held — no witness_rejected on cycle 147, and the postmortem churn (#177 fix) prevented directory-path artifacts from triggering false missing-artifact signals. The only artifact_missing was legitimate (haiku r2 genuinely failed to produce the postmortem).
- **Scope check**: `git diff main..HEAD --name-only` is empty because nothing was committed. The scope gate itself would have permitted `chimera/soak_report.py` (the only allowed code path per the charter).

## Verdict + next step

PARTIAL — the code works (4/4 green) but wasn't committed. Operator action: manually `git add chimera/soak_report.py && git commit -m "[agent] v46: chimera/soak_report.py — compose soak_summary + soak_breakdown (4/4 tests pass)"`. This converts to CONVERGED. The v46 deliverable unblocks `chimera soak report <run-id>` CLI verb (leaf pattern follow-on chip).

```
READY-FOR-REMEDIATION
verdict: PARTIAL
files_changed: 0
tests_passing: true
spend_usd: 0.03
act_cycles: 3
notes: Code written and 4/4 tests pass (pytest exit 0, cycle 147, pro tier). The haiku tier (cycles 146 r1+r2) produced 0 working code — scope_evasion then artifact_missing with 2 tool errors. The gap: `chimera/soak_report.py` was written to disk and tested but never `git add`ed or committed. A manual commit with the `[agent]` token prefix closes the gap and converts to CONVERGED. Verdict-honesty cross-check clean (ledger confirms tests_passing=true). Spend $0.03 vs $3.00 cap — well under. The friction-free substrate confirmed: no witness_rejected, no postmortem-churn artifact_missing on the converge cycle.
```
