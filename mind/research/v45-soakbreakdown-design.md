# v45 soakbreakdown design — R3 build, second real feature + 3-fix validation

**Date locked**: 2026-05-30
**Charter type**: R3 build (second real feature; v44 was the first)
**Branch prefix**: `chimera-soak/v45-soakbreakdown-*` (token `v45`)
**Scope-check binding**: prefix `v45` → `mind/research/v45-*-design.md` (this file;
leading-alnum-token rule, ADR 0146 — single-token vNN convention).

## Why v45

Two goals in one soak:

1. **A second real feature.** `chimera/soak_breakdown.py` renders a
   **finish-reason count table** from a soak's ACT-tools ledger — the
   `3 artifact_missing / 8 skipped_three_strikes / 4 stop` summary the operator
   has computed BY HAND with `jq … | sort | uniq -c` all session. It is the
   natural companion to v44's `chimera/soak_summary.py` (per-cycle table); this
   one is the aggregate view.

2. **In-loop validation of the three build-soak fixes** landed today, all of
   which engage on an R3 build that touches `chimera/*.py` + writes a postmortem:
   - **#168 over-claim-only** — a conservative `act_cycles` no longer deadlocks
     the commit (the v44-#1 failure should not recur).
   - **#173 artifact-detail ledger** — if the postmortem task churns, the new
     `missing_artifacts` per-cycle detail makes it diagnosable on the spot.
   - **#174 witness asymmetric voting** — `witness_rejected` should drop to
     near-zero on the correct diff (a single code-quality dissent no longer
     rejects), while the charter override stays armed.

## Isolation discipline (the v40 lesson)

The soak target is a **brand-new standalone module** `chimera/soak_breakdown.py`
that nothing imports at load time, tested DIRECTLY. The CLI verb
(`chimera soak breakdown <run-id>`) is a SEPARATE later chip (the `mind count`
/ `soak summary` split). A regression in the new module cannot brick the loop.

## The target (ONE new file)

**`chimera/soak_breakdown.py`** — two functions:

    def format_finish_reason_breakdown(act_rows: list[dict]) -> str: ...
    def format_soak_breakdown(mind_dir, run_id) -> str: ...

### `format_finish_reason_breakdown(act_rows)` — the test-pinned core (pure)

Counts the `finish_reason` of each ACT-cycle record and renders a markdown
table sorted by **count descending, then reason ascending** (ties
deterministic), with a `**Σ**` total row.

- Empty input → `""`.
- Otherwise, exactly (for rows with finish_reasons `[stop, stop,
  artifact_missing, stop]`):

```
| finish_reason | count |
|---|---:|
| stop | 3 |
| artifact_missing | 1 |
| **Σ** | 4 |
```

  - rows sorted by `(-count, reason)`; the Σ total is the number of records.
  - trailing newline.

### `format_soak_breakdown(mind_dir, run_id)` — the integration wrapper

Reads `<mind_dir>/soak/<run_id>/act-tools.jsonl` (via
`chimera.core.soak_ledger._read_jsonl`) and returns a headline + the table:

    # Soak <run_id> — finish-reason breakdown (<N> cycles)\n<table>

Empty/absent ledger → `# Soak <run_id> — no ACT records\n`.

## What Chimera may touch (hard cap)

- `chimera/soak_breakdown.py` — new module (CREATE).
- `tests/test_soak_breakdown.py` — READ-ONLY (on main); read to discover the
  contract; MUST NOT edit.

`chimera/cli.py`, `chimera/core/soak_ledger.py`, every other source — out of
scope. (May CALL `soak_ledger._read_jsonl`; must NOT modify it.)

## READY-FOR-REMEDIATION

<!--
ADR 0146 scope check (prefix v45 → this design note). ONE backticked code path
→ allowlist {chimera/soak_breakdown.py}. The test is NOT backticked → a staged
edit to it is refused. mind/* + .md auto-allowed. Numeric fields are
RUN-CUMULATIVE (single-build run). The gate is over-claim-only (#168): a
conservative act_cycles/spend_usd will NOT block — report the cumulative total.
-->

R3 build. The allowed code path is `chimera/soak_breakdown.py` — the agent
creates it. The pre-written test is read-only input, excluded from the
allowlist; a staged edit is refused at commit. The postmortem and other mind/
files are auto-allowed. Commit message MUST begin with the literal `[agent]`
token as its first characters.

## Pre-written test (strict-mode probe)

`tests/test_soak_breakdown.py` lands on main FAILING (module absent), gated by
`CHIMERA_V40_GATE`. Pins `format_finish_reason_breakdown` (empty, single,
sort-by-count, tie-break, Σ total) and `format_soak_breakdown` (headline +
table; empty-ledger path). Lazy import → clean assertion failure.

## Falsification gates (locked)

1. **Primary**: `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q tests/test_soak_breakdown.py` → exit 0.
2. **Scope**: diff ⊆ {`chimera/soak_breakdown.py`, postmortem.md}.
3. **Verdict-honesty**: postmortem passes Rules A–E in-loop (now over-claim-only).
4. **Cost**: ≤ $3.00.
5. **Substrate-discipline**: no ADR 0146 trip; no import-shadow; **witness_rejected
   near-zero on the correct diff** (the #174 validation signal).

## Runner

`scripts/long_cycle_soak_v45.sh` — clones the v44 single-target two-phase
runner; target `chimera/soak_breakdown.py` / the new test, run id
`v45-soakbreakdown-$STAMP`, prefix `v45`, $3.00 cap, ACT budget 600s. Launch is
a separate explicit operator action (PR #111).

## Follow-on (after the module lands)

- `chimera soak breakdown <run-id>` CLI verb (the `soak summary` leaf pattern).
