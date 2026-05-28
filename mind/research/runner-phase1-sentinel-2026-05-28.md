# Phase-1 soft-sentinel for soak runners — design note

**Date**: 2026-05-28
**Chip**: v36-postmortem follow-up B (runner-correctness defect)
**Status**: locked
**Motivating PR**: #117 (v36 micro-soak postmortem, merged at 99424b8)

## The defect (verbatim from PR #117)

> Phase 1's `ready_marker_found` exit condition checks for
> `## READY-FOR-REMEDIATION` in `INVESTIGATION_DOC` — but
> `INVESTIGATION_DOC` is set to the *input reference doc* (the F2
> retrieval ablation note), not the *output deliverable* the agent
> writes (`v36-locomo-temporal-one-item-classification.md`). The
> soft-sentinel (which IS targeted at the deliverable) is only armed
> during phase 2. So phase 1 has no path to exit on "deliverable
> landed" — it must time out via budget, wall-clock, or a watchdog.

Mechanism: `soak_extract_sentinel_path` (in `_soak_common.sh`) parses
the INBOX for the first backticked `mind/research/<name>.md` path. For
v34's INBOX that path happened to be the output deliverable (only one
such reference). For v36's INBOX the first match is
`mind/research/locomo-f2-retrieval-ablation-2026-05-27.md` — the F2
postmortem cited as background reading. The output deliverable appears
later in the INBOX prose. The extractor is positional, not semantic.

## Why PR #113's task-completion watchdog masked it (fragile)

v36 converged in 8 phase-1 iterations. PR #113's task-completion
watchdog tripped on iter 8 (6 consecutive `completed=0/M tasks` at
budget cap after grace). The fortunate alignment:

1. Agent writes the v36 deliverable file with the READY marker around
   iter 2.
2. Inbox tasks (`- [ ]` items in `INBOX.md`) all get checked off
   around the same time.
3. Subsequent iters have nothing to do: the agent emits ACT phases
   with `completed=0/0 tasks` because the task queue is empty.
4. The task-completion watchdog interprets this as a stall and aborts.

The watchdog fired correctly per its **designed** mechanism (zero
completion at budget cap). What was fortunate was step 2 — the inbox
emptying right after the deliverable lands. Under different timing
(v37's multi-item charter, slower agent, a half-completed inbox at
deliverable-write time, or a tuned-down watchdog threshold) the
alignment breaks and the phase 1 burns to the wall-clock cap before
exiting.

## The locked design

Both phases use the same `SOFT_SENTINEL_ALLOWED_FILES` +
`SOFT_SENTINEL_TEST_CMD` variables, armed by the runner before each
`phase_loop` call. `phase_loop` dispatches by the `engines_enabled`
flag it already takes:

| Phase | Engines | Check function                       | Gate                                              |
|-------|---------|--------------------------------------|---------------------------------------------------|
| 1     | OFF     | `soak_phase1_deliverable_landed`     | every allowed file exists + at least one contains `## READY-FOR-REMEDIATION` + `test_cmd` exits 0 |
| 2     | ON      | `soak_phase2_deliverable_landed`     | ≥1 `[agent]` commit + cumulative diff scoped to allowed files (+ `mind/*` auto-allow) + `test_cmd` exits 0 |

`soak_phase1_deliverable_landed` is added to `_soak_common.sh`
alongside the existing watchdog helpers. `soak_phase2_deliverable_landed`
in `soak_lib.sh` is untouched.

For v36-shape soaks (single deliverable in `mind/research/*-design.md`,
research-only, no test gate) the phase-1 arming is:

```bash
SOFT_SENTINEL_ALLOWED_FILES="mind/research/v36-locomo-temporal-one-item-classification.md"
SOFT_SENTINEL_TEST_CMD="true"
```

For v34's design-spec phase 1 (one design doc, no test gate) the
arming is the analogous v34-design.md path.

## Backward compatibility

- Runners that do **not** arm `SOFT_SENTINEL_ALLOWED_FILES` /
  `SOFT_SENTINEL_TEST_CMD` before phase 1 fall through to the
  unchanged legacy path: `INVESTIGATION_DOC` + `ready_marker_found`.
- Phase 2's mechanism is byte-for-byte unchanged. v36 already
  converged with the current phase-2 sentinel; that working surface
  is preserved.
- PR #113's task-completion watchdog stays in place as
  defense-in-depth. The two mechanisms are **complementary**:
  - phase-1 sentinel catches the **success** case (deliverable
    landed) — the path that didn't exist before.
  - task-completion watchdog catches **degenerate** stalls
    (the v35-attempt-4 pattern: cycle/spend advance while
    `completed=0/M` every iter).
- Archived runners under `scripts/archive/soak-runners/` are not
  updated per PR #100's archive policy.

## Counterfactual: v36 with the fix in place

Observed timeline (logs in PR #117):
- iter 2: agent writes
  `mind/research/v36-locomo-temporal-one-item-classification.md`
  ending in `## READY-FOR-REMEDIATION`.
- iters 3–7: ACT phases hit the 240s budget with `completed=0/0` (no
  inbox tasks left).
- iter 8: task-completion watchdog trips (`SOAK_NO_COMPLETION_THRESHOLD=6`).

With the phase-1 soft-sentinel armed against the actual deliverable
path, the exit fires on the next iter boundary after iter 2 — when
`phase_loop` checks the soft sentinel post `chimera run`. Estimated
6 fewer iters of ACT-budget burn, exit reason
`soft_sentinel_deliverable_landed` instead of `no_task_completion`,
and the postmortem table reads cleanly: phase 1 exits because the
deliverable shipped, not because nothing is happening.

## Honest disclosures

- PR #113's watchdog wasn't "accidental rescue" — it tripped per its
  designed mechanism (zero completion at budget cap). The fragile
  part is the timing alignment (inbox empties right as the
  deliverable lands), not the watchdog itself.
- This fix preserves PR #113's task-completion watchdog as
  defense-in-depth. The phase-1 sentinel catches the success case;
  the watchdog catches degenerate stalls. Together they cover both
  failure modes the v35 → v36 ladder surfaced.
- A more invasive option — move all sentinel arming into
  `_soak_common.sh` as defaults derived from a manifest, deprecate
  the per-script env-var pattern — is **deferred** to a future
  cleanup chip. This PR stays scoped to the minimum that closes the
  defect.
- The legacy `INVESTIGATION_DOC` extraction path is preserved (not
  removed). It's load-bearing for any future runner that doesn't arm
  the new sentinel; deletion belongs to the deferred cleanup chip.

## Scope of this PR

≤4 files (locked):

1. `scripts/_soak_common.sh` — add `soak_phase1_deliverable_landed`.
2. `scripts/long_cycle_soak_v34.sh` — dispatch by `engines_enabled`
   in `phase_loop` soft-sentinel block; arm phase-1 sentinel.
3. `scripts/long_cycle_soak_v36.sh` — same.
4. `scripts/test_soak_progress.sh` — cases 10–13 (sentinel fires,
   doesn't false-positive, backward-compat error paths, phase-2
   sentinel preserved).

Out of scope: agent loop, ADR 0146 scope check, PR #113 watchdog
implementation, the silent-death watchdog, any Python.

## v37 charter prerequisite

v37 (multi-item temporal-regression classification) is the next
substantive chip on the queue. Under v37 timing the inbox-empty
alignment that masked the defect in v36 is unlikely to hold, so v37
should not be chartered until this PR lands. The operator decides
the charter; this note records the operational dependency.
