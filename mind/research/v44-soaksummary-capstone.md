# v44 — CLEAN CONVERGENCE: Chimera's first REAL feature (chimera soak summary)

**Date**: 2026-05-30
**Soak**: `chimera-soak/v44-soaksummary-2026-05-30-1400` (agent commit `1684be4`)
**Charter**: `mind/research/v44-soaksummary-design.md`
**Substrate**: `8e11ee4` — the over-claim-only honesty-gate fix (#168)
**Verdict**: **CLEARED.** First real feature after the build-capability ladder.
This chip (the landing) ships the module + the `chimera soak summary` CLI verb.

## Two milestones in one run

1. **Chimera built its first real feature.** Not a contract-test toy: a genuine
   tool — `chimera/soak_summary.py` — that reads the live soak-ledger format and
   renders the iteration-vs-spend table postmortems used to fill BY HAND. The
   code is clean and idiomatic (module-level `_read_jsonl` import, typed, a Σ
   totals row, correct empty-ledger path).
2. **The over-claim-only fix (#168) is validated in-loop.** The first v44
   attempt deadlocked: a correct 6/6 build could not commit because the
   postmortem's honest-but-conservative `act_cycles` kept re-tripping the gate
   against a ledger that churn grew. This re-run, on the de-deadlocked
   substrate, produced a clean `[agent]` commit with **zero
   `postmortem_dishonest` firings** — the agent again reported a conservative
   `act_cycles: 3` (vs ledger 15), now TOLERATED as an under-claim. Same control
   variable, opposite outcome.

## The five gates

| Gate | Result | Evidence |
|---|---|---|
| 1 Primary | **PASS** | `CHIMERA_V40_GATE=1 … pytest tests/test_soak_summary.py` → **6 passed** |
| 2 Scope | **PASS** | one code file `chimera/soak_summary.py` + mind/* (auto-allowed); one `[agent]` commit |
| 3 Verdict-honesty | **PASS** | `tests_passing: true` ↔ ledger `True`; CONVERGED earned; **0** dishonest firings (under-claim tolerated post-#168) |
| 4 Cost | **PASS** | **$0.24** / $3.00 |
| 5 Substrate-discipline | **PASS** | no guard trip blocked convergence |

## The CLI verb works end-to-end

`chimera soak summary <run-id>` (thin `cli.py` leaf wrapper over
`format_soak_summary`, the `mind count` pattern) renders the real table from a
run's ledger — verified against this very run:

```
# Soak v44-soaksummary-2026-05-30-1400 — 15 ACT cycles
| ACT cycle | tool calls | tool errors | tool ms | finish_reason | completed |
|---:|---:|---:|---:|---|:---:|
| 146 | 12 | 0 | 980.567 | stop | Y |
| 146 | 44 | 7 | 2072.572 | artifact_missing | N |
…
```

The feature closes the loop on its own motivation: it is the tool that lets a
postmortem report the iteration-vs-spend numbers *by reading them*, instead of
the by-hand estimation that drove the entire honesty-gate thread.

## What the conservative loop did, again

The first real target surfaced a deep substrate defect (the act_cycles
moving-target deadlock), it was diagnosed and fixed (over-claim-only, #168),
and the re-run *proved* the fix while delivering a correct feature. The same
discipline that de-risked the ladder de-risked the jump to real work.

## Honest caveat (not a gate failure)

Postmortem churn persists — `8 skipped_three_strikes` + `3 artifact_missing`
on the postmortem task (as in v43/the first v44 attempt). The BUILD is
near-one-shot; the writeup remains the churny tail. With the gate no longer
deadlocking on it, the churn no longer blocks convergence, but it is a standing
cost worth a future look (the postmortem task structure, not the honesty gate).

## What this chip lands

- `chimera/soak_summary.py` — the agent's module, verbatim + provenance.
- `chimera/cli.py` — `chimera soak summary <run-id>` leaf wrapper.
- `tests/test_soak_summary.py` — un-gated; 7 tests (6 contract + 1 CLI verb).
- `mind/research/soak-summary-postmortem.md` — the soak postmortem.
- `mind/research/v44-soaksummary-capstone.md` — this record.

## Next

- The pivot to real targets is proven. Natural follow-ons (operator's call):
  the deferred **spend column** for `soak summary`; the **postmortem-churn**
  investigation (the standing tail cost); or the next real feature/refactor
  (e.g. the `write_targets` root-cause fix, or the witness over-rejection).
