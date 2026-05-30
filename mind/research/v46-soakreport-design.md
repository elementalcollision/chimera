# v46 soakreport design — R3 build, trio capstone + friction-free-substrate confirmation

**Date locked**: 2026-05-30
**Charter type**: R3 build (third real feature; v44 summary, v45 breakdown)
**Branch prefix**: `chimera-soak/v46-soakreport-*` (token `v46`)
**Scope-check binding**: prefix `v46` → `mind/research/v46-*-design.md` (this file).

## Why v46

The capstone of the soak-analysis trio: `chimera soak report <run-id>` — one
command that shows the **full** soak health view by composing v44's per-cycle
iteration table and v45's finish-reason breakdown under one headline. Replaces
running two verbs with one.

It is also the first build to **import existing Chimera modules** (the two pure
cores `format_iteration_table` from `chimera/soak_summary` and
`format_finish_reason_breakdown` from `chimera/soak_breakdown`). That exercises
a bit more of the substrate than a self-contained module — and it is the first
build to run on the FRICTION-FREE substrate: post-#177 the postmortem churn is
gone, post-#174 witness over-rejection is gone, post-#168 the over-claim
deadlock is gone. v46 confirms a near-zero-friction convergence (expect 0
`artifact_missing` on the postmortem, 0 `witness_rejected`, a clean commit).

## Isolation discipline

`chimera/soak_report.py` is a brand-new standalone module nothing imports at
load time, tested DIRECTLY. It IMPORTS two existing modules (read-only); it must
NOT modify them. The CLI verb (`chimera soak report`) is a separate later chip.

## The target (ONE new file)

**`chimera/soak_report.py`** — two functions:

    def format_report_body(act_rows: list[dict]) -> str: ...
    def format_soak_report(mind_dir, run_id) -> str: ...

### `format_report_body(act_rows)` — the test-pinned core (pure)

Composes the two existing pure cores under section headers. Imports at module
top: `from chimera.soak_summary import format_iteration_table` and
`from chimera.soak_breakdown import format_finish_reason_breakdown`.

- Empty input → `""`.
- Otherwise, exactly:

      ## Iterations\n\n<iteration_table>\n## Finish reasons\n\n<breakdown_table>

  where `<iteration_table>` is `format_iteration_table(act_rows)` (already ends
  in `\n`) and `<breakdown_table>` is `format_finish_reason_breakdown(act_rows)`
  (already ends in `\n`). I.e. `"## Iterations\n\n" + iter + "\n## Finish
  reasons\n\n" + breakdown`.

### `format_soak_report(mind_dir, run_id)` — the integration wrapper

Reads `<mind_dir>/soak/<run_id>/act-tools.jsonl` (via
`chimera.core.soak_ledger._read_jsonl`):

- empty/absent → `# Soak <run_id> — no ACT records\n`
- otherwise → `# Soak <run_id> — report (<N> cycles)\n\n` + `format_report_body(rows)`

## What Chimera may touch (hard cap)

- `chimera/soak_report.py` — new module (CREATE).
- `tests/test_soak_report.py` — READ-ONLY (on main); read to discover the
  contract; MUST NOT edit.

`chimera/soak_summary.py`, `chimera/soak_breakdown.py`, `chimera/cli.py`,
`chimera/core/soak_ledger.py`, every other source — out of scope (may IMPORT
the first two; must NOT modify them).

## READY-FOR-REMEDIATION

<!--
ADR 0146 scope check (prefix v46 → this design note). ONE backticked code path
→ allowlist {chimera/soak_report.py}. The test is NOT backticked → a staged
edit is refused. mind/* + .md auto-allowed. Numeric fields run-cumulative;
gate is over-claim-only (#168) — a conservative count will NOT block.
-->

R3 build. The allowed code path is `chimera/soak_report.py` — the agent creates
it, importing the two existing pure cores read-only. The pre-written test is
read-only input, excluded from the allowlist. The postmortem and other mind/
files are auto-allowed. Commit message MUST begin with the literal `[agent]`
token as its first characters.

## Pre-written test (strict-mode probe)

`tests/test_soak_report.py` lands on main FAILING (module absent), gated by
`CHIMERA_V40_GATE`. Pins `format_report_body` (empty; the composed two-section
body) and `format_soak_report` (headline + body; empty-ledger path). Lazy
import → clean assertion failure.

## Falsification gates (locked)

1. **Primary**: `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q tests/test_soak_report.py` → exit 0.
2. **Scope**: diff ⊆ {`chimera/soak_report.py`, postmortem.md}.
3. **Verdict-honesty**: postmortem passes Rules A–E in-loop.
4. **Cost**: ≤ $3.00.
5. **Substrate-discipline**: no ADR 0146 trip; no import-shadow; **0
   witness_rejected, near-0 artifact_missing** — the friction-free confirmation.

## Runner

`scripts/long_cycle_soak_v46.sh` — clones the v45 single-target runner; target
`chimera/soak_report.py` / the new test, run id `v46-soakreport-$STAMP`, prefix
`v46`, $3.00 cap, ACT budget 600s. Launch is a separate explicit operator action.

## Follow-on

- `chimera soak report <run-id>` CLI verb (the leaf pattern).
