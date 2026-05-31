# ADR 0156 — Soak soft-sentinel measures against the build base (A1 reliability)

**Status**: Accepted (2026-05-31). Tier-A reliability fix from the
robustness-to-production roadmap.

## Context

The pure (`autocommit=0`) `durparse` charter build produced a clean agent
self-commit (`e7348a7 [agent] build chimera/durparse.py`, allowed by the ADR
0146 scope check) — yet phase 2 still exited `no_forward_progress` instead of
`soft_sentinel_deliverable_landed`. A convergence-detection gap: the build
succeeded but the runner did not recognise it.

Root cause: `soak_phase2_deliverable_landed` (`scripts/soak_lib.sh`) hard-coded
`main..HEAD` for both its "≥1 `[agent]` commit" check and its "diff touches only
allowlisted files" check. The v46 soaks build from `main`, so that was correct
there. But the generic charter-build soak (ADR 0155) builds from a
`CHARTER_BASE` branch that ALREADY carries the materialized acceptance test +
design note. Measuring against `main` pulls those (un-allowlisted) files into the
diff → the scope check fails → the sentinel refuses → a perfectly clean commit
falls through to `no_forward_progress`.

## Decision

Add an optional `base_ref` parameter (4th arg) to
`soak_phase2_deliverable_landed`, defaulting to `main` (so every existing v46
caller is unchanged). The generic charter runner passes `CHARTER_BASE`, so the
deliverable diff carries only the delta the agent actually produced.

## Consequences

### Pros

- Closes the convergence gap: a successful charter build now exits
  `soft_sentinel_deliverable_landed` (clean, fast), not `no_forward_progress`.
- Zero v46 behavior change — the default base is `main`.
- Makes every future charter build's *success* legible, which is a prerequisite
  for the Tier-B production-value work (you cannot build on a loop whose success
  signal is unreliable).

### Cons / honest disclosures

- This fixes the phase-2 sentinel. Phase 1 still exits `no_forward_progress`
  after the build lands (the postmortem-ready-marker sentinel timing, a
  pre-existing v46 pattern) — cosmetic (the module is built + green) but a
  separate cleanup if we want phase 1 to also exit cleanly.
- The base-ref is plumbed only through the phase-2 sentinel here; if other
  base-relative checks surface the same hardcoded-`main` assumption, they get the
  same treatment.

## Test coverage

`tests/test_soak_sentinel_base_ref.py` (4): a temp repo mirroring the charter
build (base branch carries the materialized test; an `[agent]` build commit on
top) — the sentinel FIRES with `base=build-base`, MISSES with `base=main` (the
bug), the default 3-arg form equals `base=main` (backward compat), and a failing
test blocks the sentinel.

## References

- [ADR 0155](./0155-generic-charter-build-soak.md) — the generic runner whose
  non-main base surfaced this.
- `mind/research/pure-autonomous-loop-durparse-2026-05-31.md` — the run where the
  `no_forward_progress`-after-success was observed.
- `mind/research/robustness-to-production-roadmap-2026-05-31.md` — A1.
