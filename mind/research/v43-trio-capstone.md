# v43 attempt #1 — CLEAN CONVERGENCE at the parallel rung (the build ladder closes)

**Date**: 2026-05-29
**Soak**: `chimera-soak/v43-trio-2026-05-30-0052` (agent commits `66a3f51`, `c857893`, `d09e88f`)
**Charter**: `mind/research/v43-parallel-builds-design.md`
**Substrate**: fully hardened (H1+H2+H3, B1/B2, numeric-honesty drift chip) at `00c486c`
**Verdict**: **CLEARED.** All five locked gates. The final ladder rung — three
independent single-file builds in one soak (N=3). This chip (A⁗) lands all
three modules on main and closes the build-capability ladder.

## The five gates

| Gate | Result | Evidence |
|---|---|---|
| 1 Primary ×3 | **PASS** | `CHIMERA_V40_GATE=1 … pytest tests/test_strcase.py tests/test_numfmt.py tests/test_seqstats.py` → **17 passed** |
| 2 Scope | **PASS** | diff = exactly the 3 modules + 3 postmortems; **three independent `[agent]` commits** (one per module, not bundled — exactly as charter required) |
| 3 Verdict-honesty ×3 | **PASS (substance)** | all three postmortems `tests_passing: true` ↔ ledger `tests_passed_any: True` (7 test-runs, ≥1 passing) |
| 4 Cost | **PASS** | **$0.41** / $6.00 cap |
| 5 Substrate-discipline | **PASS** | no ADR 0146 trip; no `fix_without_test` / `commit_bypasses_index` / import-shadow |

## What this answers — the ladder's closing question

**Can the autonomous loop carry three independent build charters through one
soak?** **Yes.** The loop built each target correctly and committed three clean
per-module commits, never dropping or conflating a target:

- `chimera/strcase.py` (`to_snake`, `to_camel`) — green build cycle 1, despite
  a `witness_rejected` false-positive on the first witness pass (re-verified
  green cycle 6).
- `chimera/numfmt.py` (`human_bytes`, `clamp`) — the cleanest build, green
  cycle 2, zero errors, zero rejections.
- `chimera/seqstats.py` (`running_max`, `dedupe_stable`) — green cycle 3 after
  one absent-file retry.

20 ACT cycles, 127 tool calls (6 errors), $0.41 total. **Task management at
N=3 works** — the variable v43 escalated (fan-out breadth) held.

### The ladder, complete

| rung | soak | result |
|---|---|---|
| 1 tiny | v40′ | CLEARED ($0.31) |
| 2 moderate | v41 | CLEARED ($0.137) |
| 3 multi-file | v42 | CLEARED ($0.16) |
| 4 parallel (N=3) | **v43** | **CLEARED ($0.41)** |

Four clean convergences. The original question — *"what happens when we ask
Chimera to build something?"* — is answered across the full difficulty ladder:
it builds correct net-new code (tiny → edge-case → multi-file with an authored
import boundary → three independent modules at once), iterates to green, and
commits scope-clean with honest reporting on the load-bearing claim.

## The finding (falsification-honest): the numeric-honesty gate was DORMANT

The drift chip (Rules D/E: checked `act_cycles` / `spend_usd`) was built
*specifically* for this rung, to make three concurrent postmortems trustworthy.
**It never fired** — and the run shows why:

- **`write_targets` was empty (length 0) on all 20 ACT records** — including
  the build cycles that demonstrably wrote modules. The write-target-based
  in-loop gates (import-shadow + postmortem honesty, including Rules D/E)
  inspect `write_targets`, so with it empty they no-op'd all run.
- Consequence: the three postmortems' numeric claims went **un-validated**.
  All three claim per-build `act_cycles: 7` / `spend_usd: 0.09` — sensible
  *per-build* attributions (7+7+7 ≈ 20 cumulative; spend sums to $0.27 vs
  $0.41 actual, ~$0.14 unattributed to phase-2 + the 8 postmortem-writing
  `skipped_three_strikes` churn cycles) — but using **per-build semantics**,
  not the cumulative-run semantics Rules D/E assume. Had the gate run, it would
  have compared `7` against cumulative `20` and likely tripped.

This does **not** falsify the build: the modules are correct (proven by the
independent pytest + scope gates, which do not depend on `write_targets`), and
`tests_passing` — the load-bearing honesty field — is genuinely accurate on all
three. But the honesty *substrate* did not get exercised on this rung. It
raises an R2 follow-up (chip filed): **why is `write_targets` empty across a
soak run — is it v43-specific or a general soak-ledger gap — and should the
write-target gates fall back to a ledger / phase-2-diff source when it is
empty?** Sub-question: define `act_cycles` / `spend_usd` as per-build vs
cumulative for fan-out soaks so the gate's comparison is well-posed.

This is exactly the kind of substrate-coverage gap the conservative N=1→N=3
ladder is designed to surface — cheaply, on a correct build, before any larger
fan-out depends on the gate.

## What this chip (A⁗) lands

- `chimera/strcase.py`, `chimera/numfmt.py`, `chimera/seqstats.py` — the three
  agent-authored modules, verbatim + provenance docstrings.
- `tests/test_strcase.py`, `tests/test_numfmt.py`, `tests/test_seqstats.py` —
  un-gated (the `CHIMERA_V40_GATE` skipif removed now that the modules exist);
  17 contract tests run in CI.
- `mind/research/v43-{strcase,numfmt,seqstats}-postmortem.md` — the three soak
  postmortems.
- `mind/research/v43-trio-capstone.md` — this record.

## Next

- **Build-capability ladder: CLOSED.** Rungs 1–4 all CLEARED.
- **R2 follow-up (chip filed):** the `write_targets`-empty / dormant-honesty-gate
  finding above — investigate root cause + a ledger fallback for the
  write-target gates, and resolve per-build vs cumulative numeric semantics for
  fan-out soaks.
