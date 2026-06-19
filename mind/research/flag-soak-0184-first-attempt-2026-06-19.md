# Flag soak — TOOL_PREFILTER (ADR 0184), first attempt (2026-06-19): INCONCLUSIVE

First keyed flag-OFF/ON soak for `CHIMERA_TOOL_PREFILTER`, qwen-led, roman probe,
in a supervised scheduler-off window. Scored by `chimera cost-delta`.

## Raw

| arm | gate | calls | input tok | total tok | cost |
|---|---|---|---|---|---|
| OFF (baseline) | **fail** | 38 | 167,068 | 182,307 | $0.0353 |
| ON (treatment) | pass | 45 | 313,630 | 342,928 | $0.0993 |

`cost-delta` verdict: "treatment COSTLIER by 181%" — **not valid evidence.**

## Why it's inconclusive (two confounds)

1. **Unequal outcomes.** The OFF arm *failed the gate* (n=1 run-to-run variance —
   qwen wrote a roman impl that didn't pass) while ON passed. The two runs did
   different amounts of work, so the delta measures "OFF gave up early," not the
   flag. A flag soak is only valid when **both arms reach the same outcome**
   (both green).
2. **Wrong signal granularity.** TOOL_PREFILTER's lever is *tool-definition*
   input tokens (pruning advertised tool schemas). On a real coding soak, total
   input tokens are dominated by conversation history + file contents, so the
   tool-def savings are buried — ON even showed *more* input tokens (314K vs
   167K), purely because it ran more rounds. Total-token cost-delta cannot
   isolate this flag's effect.

## Implications for 0184/0185 graduation method

The cost-delta analyzer is sound, but the *soak design* for these flags needs:
- **Both-arm gate-pass required** — discard/retry any run where an arm fails;
  ideally **multi-trial** (median over ≥3) given the variance.
- **Signal isolation for TOOL_PREFILTER** — measure tool-definition input tokens
  specifically (e.g. instrument the prefilter to log pruned-schema token counts),
  not total tokens. COMPLEXITY_ROUTING (0185) is different again — it trades cost
  for quality, so its evidence is rounds/gate-pass at a controlled task.

## Disposition
No graduation. No ledger/main impact (the one-off driver bypassed
`crawl record`); worktrees pruned, scheduler re-enabled. ADR 0184 Evidence
section updated to require the refined method before re-attempting.
