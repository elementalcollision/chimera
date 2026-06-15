# mind/ab/ — model A/B probes (ADR 0183 A.1)

Specs here are **A/B probes**, not daily-CRAWL tasks. They live *outside*
`mind/backlog/` so the daily picker (`chimera backlog next`) never auto-runs
them. `scripts/ab_soak.sh` runs a probe through the real soak loop **twice** —
once per model arm — and scores the two runs head-to-head.

## Run an A/B

```bash
# Validate the scenario (no spend): resolves the spec + both arm configs.
AB_SPEC=mind/ab/codetier-probe.md TASK_DRYRUN=1 bash scripts/ab_soak.sh

# Live run (spend + ~2 soaks of wall): pins ACT to each model, scores, records.
AB_SPEC=mind/ab/codetier-probe.md bash scripts/ab_soak.sh
```

Default arms — the only models that differ between the `code` and `sonnet`
tiers (their leads):

| arm | model | meaning |
|---|---|---|
| A (`incumbent`) | `deepseek/deepseek-v4-pro` | today's CRAWL lead (sonnet lead) |
| B (`code`) | `moonshotai/kimi-k2.7-code` | the code-tier candidate lead |

Override with `AB_ARM_A_MODEL` / `AB_ARM_B_MODEL` (any `chimera tiers` model
or alias). Any `real_task_soak.sh` knob (caps, walls) passes through to both
arms unchanged.

## What it measures (the decision rule)

A **landed** change = gate pass (ruff + pytest, narrowed to the spec) AND ≥1
`[agent]` commit, with the in-loop faithfulness + critic gates applied to both
arms identically. The verdict:

- both landed → **cheaper wins** (cost-per-landed-change),
- only one landed → that arm wins,
- neither → inconclusive (re-run or fix the spec).

Both runs are recorded into the outcome ledger (`chimera crawl report`) with
arm-tagged run_ids, so evidence accrues across re-runs. This is the gate ADR
0183 A.1 puts on the code-tier default-routing flip: route CRAWL ACT at the
`code` tier only on a kimi win (or parity at lower cost).

## Repeatable by construction

A probe stays `done: false` and is **never merged** — each arm builds in a
throwaway worktree and `ab_soak.sh` leaves both for review (nothing is pushed).
Because the deliverable never lands on `base`, the spec's gate stays red there,
so the probe can be re-run unchanged whenever a new code model is ingested.

## Writing a new probe

Same frontmatter as a backlog spec (see `mind/backlog/README.md`), with FIXED
acceptance criteria so the two arms build identical behaviour and only the
model varies. Make it gate-visible (the new test absent on `base`) and pick a
task with enough logic that two models genuinely differentiate.
