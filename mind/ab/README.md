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

Each arm writes its OWN gate test, so the in-loop gate proves only that the
arm's tests pin its OWN implementation — NOT that the implementation meets the
external spec. A model can therefore "pass" by under-implementing and
under-testing in tandem (this is exactly what happened in the first run —
deepseek skipped a unit + the ordering rules and self-graded green; see
`mind/research/ab-codetier-first-run-2026-06-15.md`). So **quality is graded
separately**, against a canonical acceptance test:

- Put a `<spec>.accept.py` next to the spec (e.g. `codetier-probe.accept.py`),
  or set `AB_ACCEPT=<path>`. It is the single source of truth for the spec's
  acceptance criteria — a normal pytest file importing the produced module.
- After each arm, `ab_soak.sh` copies it into that arm's worktree and runs it
  against the arm's produced code — IDENTICAL test, both arms.

A **landed** change = gate pass AND ≥1 `[agent]` commit. The verdict, when an
accept test is present (**quality-first, so cost can't win by doing less**):

- higher **spec-pass** wins,
- equal spec-pass → **cheaper** wins (cost-per-landed at equal quality),
- neither landed → inconclusive.

Without an accept test it falls back to a cost-only verdict, clearly labelled
`(UNGRADED)` — do not make a routing decision on an ungraded run.

Both runs are recorded into the outcome ledger (`chimera crawl report`) with
arm-tagged run_ids, so evidence accrues across re-runs. This is the gate ADR
0183 A.1 puts on the code-tier default-routing flip: route CRAWL ACT at the
`code` tier only on a graded win (or parity at lower cost).

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
