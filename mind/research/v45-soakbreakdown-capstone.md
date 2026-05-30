# v45 — CLEAN CONVERGENCE: 2nd real feature + all 3 build-soak fixes validated

**Date**: 2026-05-30
**Soak**: `chimera-soak/v45-soakbreakdown-2026-05-30-1654` (agent commit `6b1ade6`)
**Charter**: `mind/research/v45-soakbreakdown-design.md`
**Verdict**: **CLEARED.** Second real feature; and the in-loop validation soak
for the three build-soak fixes landed today. This chip lands the module + the
`chimera soak breakdown` CLI verb.

## The five gates

| Gate | Result | Evidence |
|---|---|---|
| 1 Primary | **PASS** | `CHIMERA_V40_GATE=1 … pytest tests/test_soak_breakdown.py` → **6 passed** |
| 2 Scope | **PASS** | one code file `chimera/soak_breakdown.py` + mind/*; one `[agent]` commit |
| 3 Verdict-honesty | **PASS** | `tests_passing: true` ↔ ledger `True`; CONVERGED earned; **0 dishonest** |
| 4 Cost | **PASS** | **$0.27** / $3.00 |
| 5 Substrate-discipline | **PASS** | **0** witness / scope / import / dishonest trips |

## The three fixes — all confirmed in-loop

| Fix | Validation signal (this run) | Prior behavior |
|---|---|---|
| **#168 over-claim-only** | committed CONVERGED with a conservative `act_cycles: 3` (vs ledger 15), **0 `postmortem_dishonest`** | v44 attempt #1 DEADLOCKED here |
| **#174 witness asymmetric** | **0 `witness_rejected`** on the correct diff | v42/v43/v44 all churned on it |
| **#173 artifact-detail** | recorded `missing_artifacts` per churn cycle → diagnosed the cause (below) | the cause was previously invisible |

## The payoff: the postmortem-churn root cause, finally diagnosed

The #173 instrumentation paid off on the very next soak. The churn cycles'
`missing_artifacts` show:

```
cycle 146 (max_rounds):      …postmortem.md, mind/soak/<run-id>/
cycle 147 (artifact_missing): mind/soak/<run-id>/
cycle 148 (artifact_missing): mind/soak/<run-id>/
```

**`expected_artifacts` over-captures the `mind/soak/<run-id>/` DIRECTORY path** —
the INBOX says "fill the table from the ledgers under `mind/soak/<run-id>/`", and
the artifact-path extractor lifts that directory reference as an expected
deliverable. `check_artifacts` then flags it "missing" because it is a directory,
not a non-empty FILE (`p.is_file()` is False) → `artifact_missing` fires every
postmortem cycle, even though the real postmortem `.md` is fine → the churn
(`2 artifact_missing` + `8 skipped_three_strikes`) that has taxed every soak
since v41.

The fix is narrow and clear: `expected_artifacts` / `check_artifacts` must skip
directory-shaped paths (those ending in `/`). Landed as a separate chip.

## The module

Clean and idiomatic: counts `finish_reason` via `Counter`, sorts by count desc
then reason asc, Σ total; reads the ledger via `_read_jsonl`. The aggregate
companion to v44's per-cycle `soak_summary` — `chimera soak breakdown <run-id>`
renders the `3 artifact_missing / 8 skipped_three_strikes / 4 stop` summary the
operator computed by hand all session.

## What this chip lands

- `chimera/soak_breakdown.py` — the agent's module, verbatim + provenance.
- `chimera/cli.py` — `chimera soak breakdown <run-id>` leaf wrapper.
- `tests/test_soak_breakdown.py` — un-gated; 7 tests (6 contract + 1 CLI verb).
- `mind/research/v45-soakbreakdown-postmortem.md` + this capstone.

## Next

- Land the **postmortem-churn fix** (directory-path skip in `expected_artifacts`)
  — diagnosed by #173 here, retires the churn for all future soaks.
