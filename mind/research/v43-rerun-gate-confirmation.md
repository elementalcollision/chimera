# v43 re-run — empirical confirmation the honesty gate is no longer dormant

**Date**: 2026-05-29
**Soak**: `chimera-soak/v43-trio-2026-05-30-0208` (run id `v43-trio-2026-05-30-0208`)
**Substrate**: `2d08f29` — H1/H2/H3 + drift chip + the v43 R2 dormancy fix
(PR #163 postmortem gate, #164 import-shadow gate + cumulative semantics)
**Mode**: `CHIMERA_RERUN_STRIP_TARGETS=1` — targets stripped at provisioning so
the build is genuine (the modules are already on main after the A⁗ landing #162).
**Purpose**: NOT a landing (nothing new to bank). The deliverable is *evidence*
that the now-non-dormant honesty gate fires IN-LOOP, closing the v43 finding
empirically rather than by post-hoc operator review.

## The decisive comparison

| | original v43 (`…-0052`) | re-run (`…-0208`, post-fix) |
|---|---|---|
| `write_targets` on ACT records | empty (0) on all 20 | **empty (0) on all 11** |
| `postmortem_dishonest` firings | **0 (gate DORMANT)** | **1 — fired at cycle 153** |
| postmortem numeric claims | per-build `act_cycles: 7` / `$0.09` | cumulative `act_cycles: 6` / `$0.74` (identical across all 3) |
| build outcome | 17/17, 3 commits | 17/17, 3 commits |

**The control variable held and the outcome flipped.** `write_targets` was
empty in BOTH runs — confirming the root-cause diagnosis (the soak agent writes
via the `shell` tool, excluded from `_WRITING_TOOL_NAMES`, so the in-loop
signal is always empty). In the original run that left the gate dormant and a
dishonest per-build postmortem shipped un-validated. In the re-run, on the
identical empty-`write_targets` condition, the gate **still fired** — because
the `git status` fallback (#163/#164) found the on-disk postmortem regardless
of which tool wrote it. The fix does exactly what it was designed to do.

## What the gate caught

At cycle 153 the gate raised `postmortem_dishonest` on a postmortem draft whose
numbers did not match the then-current ledger, forcing a correction. The final
committed postmortems report **run-cumulative** numbers (`act_cycles: 6`,
`spend_usd: 0.74`, identical across all three) — the convention locked in #164,
which the runner INBOX now instructs. Contrast the original run, where each
postmortem carried a *per-build slice* (7 / $0.09) that the dormant gate never
examined.

## Honest caveats (not gate failures)

1. **Write-time vs end-of-run staleness persists — and is inherent.** The final
   postmortems claim `act_cycles: 6`; `summarize_run` at run-end reports 11. The
   gate validates the claim against the ledger AT WRITE TIME (when ~6 cycles had
   executed), then the postmortem-writing churn itself (cycles 148–153:
   `artifact_missing` ×3, `max_rounds`, the `postmortem_dishonest` rewrite) grew
   the ledger to 11. A postmortem written before the run ends cannot know the
   final count; the gate enforces write-time consistency, which is the best
   achievable in-loop. This is the nature of the metric, not dishonesty.
2. **Higher cost / more churn.** $0.97 vs the original $0.41 — a live gate adds
   friction (the forced rewrite + artifact churn). Expected and acceptable: the
   gate trades a little spend for validated honesty.
3. **One commit lost its `[agent]` prefix** (`v43 seqstats: converged module …`
   instead of `[agent] …`). A charter-format deviation; the phase-2 sentinel was
   still satisfied by the other two `[agent]` commits. Minor, worth a future
   INBOX nudge.

## Verdict

**Confirmed.** The honesty substrate is no longer dormant: with `write_targets`
empty (the original failure condition), the gate now fires in-loop via the git
fallback, catches a dishonest draft, and the corrected postmortems carry the
locked run-cumulative numbers. The v43 R2 finding is closed empirically, not
just by code review.

## What this chip lands

- `scripts/long_cycle_soak_v43.sh` — the opt-in `CHIMERA_RERUN_STRIP_TARGETS`
  knob (strip targets at provisioning to re-run a build charter as a genuine
  rebuild). Default off → first-run behavior unchanged.
- this confirmation record.

The re-run worktree was pruned (nothing to land — the modules are already on
main from #162). Build-capability ladder: CLOSED. Honesty substrate: validated.
