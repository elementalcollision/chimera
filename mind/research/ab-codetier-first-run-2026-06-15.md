# Code-model A/B — first live run (2026-06-15)

**Scenario:** `scripts/ab_soak.sh` on `mind/ab/codetier-probe.md`
(`parse_duration` — compound duration → seconds). Arms pinned via
`CHIMERA_ACT_FORCE_MODEL`. ADR 0183 A.1.

## Raw outcome (outcome ledger)

| arm | model | in-loop gate | committed | cost_usd |
|---|---|---|---|---|
| incumbent | deepseek/deepseek-v4-pro | pass | 1 | 0.1402 |
| code | moonshotai/kimi-k2.7-code | pass | 1 | 0.3478 |

`ab_soak.sh`'s auto-verdict (cost-only, both-landed): **A cheaper → A wins.**

## The auto-verdict is wrong on substance

Both arms wrote their OWN `tests/test_duration.py` (Design 2). Graded against
the spec's **canonical** acceptance cases (neutral to both arms):

| arm | model | spec cases passed |
|---|---|---|
| incumbent | deepseek/deepseek-v4-pro | **11/16** |
| code | moonshotai/kimi-k2.7-code | **16/16** |

deepseek's failures (all spec-required, all missed by its self-authored test):
- `"2d"`, `"1d2h3m4s"` → raised instead of computing — **`d` unit not implemented**.
- `"30m1h"`, `"1h1h"` → returned a sum instead of `ValueError` — **no
  descending-order / no-repeat enforcement**.
- `None` → `TypeError` instead of the spec's `ValueError`.

kimi implemented the full spec (all four units, strict ordering, repeat
detection, junk detection, `ValueError` for non-string) — 16/16.

## Findings

1. **Model signal (suggestive, real):** on a fixed-spec coding task,
   kimi-k2.7-code produced a complete, correct, spec-faithful implementation;
   deepseek-v4-pro produced a 69%-correct one. Kimi's 2.5× cost bought
   correctness. This *supports* the code-tier thesis — but see #2 before
   acting on it.

2. **Harness defect (the important one):** Design 2 (agent authors its own
   gate test) lets a model pass by **under-implementing and under-testing in
   tandem**. The in-loop faithfulness/critic gates check *internal* consistency
   (do the tests pin the implemented behaviour?), NOT conformance to the
   external spec — so a weak-impl + weak-test pair sails through. Cost-only
   scoring is therefore **gameable**: the cheaper arm can be cheaper precisely
   because it did less. The cost number is only comparable at equal quality.

## Decision

- **Do NOT flip code-tier default routing on this run.** The quality signal
  favours kimi, but the run is not decision-grade: quality wasn't held equal.
- **Fix the scenario:** add a fixed **acceptance** grade — a canonical spec
  test the operator writes once, run against each arm's produced module after
  the soak. Verdict becomes: highest spec-pass wins; cost breaks ties at equal
  quality. (Implemented as `*.accept.py` + accept-grading in `ab_soak.sh`.)
- **Re-run** with accept-grading before the routing decision. Expectation from
  this run: kimi wins on correctness; the real question becomes whether its
  correctness premium is worth the cost on a representative task mix.

## Operational

Both arms ran clean (worktrees, distinct branches/run_ids, ledger records,
manual-handoff — nothing merged). Wall: deepseek ~20m, kimi ~14m. The
`RUN_ID_SUFFIX` disambiguation and `_forced_rung` OpenRouter resolution both
worked as designed. kimi needs token headroom (front-loads reasoning before
code) — ran fine at `CHIMERA_ACT_MAX_TOKENS=8192`.
