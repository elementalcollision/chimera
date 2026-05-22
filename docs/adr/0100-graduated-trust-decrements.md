# ADR 0100 — Graduated trust decrements by escalation severity

**Status:** Accepted (v4.93.0)
**Date:** 2026-05-22
**Supersedes:** ADR 0003 §"Trust tiers" (uniform decrement)
**Related:** ADR 0095 (ungrounded citation), ADR 0096 (scope evasion),
ADR 0099 (fix-without-test)

## Context

Through v4.92, every trust-affecting escalation cost the agent one tier,
regardless of what the escalation actually signified. The drift path in
`_apply_decision` (DEMOTE_PLAN → `TrustManager.demote()`) was the only
trust-decrementing route from ACT-phase failures, and it was uniform.

Soak v7 run-3 exposed the calibration gap. During phase-1 grounding
investigation:

1. ungrounded_citation fired (v4.83 caught fabricated symbols)
2. agent retried, fabricated again
3. ungrounded_citation fired
4. agent retried, fabricated again
5. ungrounded_citation fired
6. agent retried, grounded correctly — phase-1 deliverable LANDED
7. scope_evasion on a downstream task

Trust collapsed T5 → T0 LOCKED across these events. The READY-FOR-
REMEDIATION sentinel was already in place, but the agent could not
transition to phase-2 because it was in observer mode.

The fixture (preserved at
`/Users/dave/chimera-soak-v7-2026-05-22-1331/state/trust_state.json`)
shows the literal demote sequence. The system was working as designed —
detector caught the bad citations, model self-corrected — but the trust
mechanism penalized the recovery loop the same way it penalizes a
silent failure.

## Decision

Replace uniform decrement with a `finish_reason → trust_delta` table,
applied directly after each ACT result (not indirectly via drift).

```text
silent_failure       → −2   (wrote-but-claimed-not / didn't-do-the-work)
scope_evasion        → −2   (wrote to the wrong file)
artifact_missing     → −1   (incomplete delivery vs. contract)
fix_without_test     → −1   (incomplete delivery vs. contract)
degenerate_loop_abort→ −1   (capability/stability signal)
ungrounded_citation  →  0   (draft-quality; model self-corrects)
max_rounds           →  0   (capability/budget — handled by tier-escalation memory)
length               →  0   (capability/budget — handled by tier-escalation memory)
```

Reasons not in the table demote 0 by default. Unknown signals must
*not* silently drain trust; new finish_reasons get evaluated before
they enter the table.

### Implementation

- `chimera/trust/manager.py`:
  - new module-level `FINISH_REASON_TRUST_DELTAS`
  - new `TrustManager.apply_finish_reason(finish_reason, *, reason_suffix)`
    that demotes `delta` tiers (clamped at T0) and returns the actual
    number applied. Each demote is its own history event tagged with
    `finish_reason=...` for forensic clarity.
- `chimera/core/loop.py::_phase_act`:
  - after each non-completed `ActResult`, call
    `self._trust.apply_finish_reason(result.finish_reason, ...)` and
    log if demotion occurred.

The drift → `TrustManager.demote()` path in `_apply_decision` is
preserved untouched. Drift represents an orthogonal signal (vocab /
tool-distribution distance), and ADR 0001's lockdown contract still
applies. The two paths are now layered: drift catches *behavioral*
divergence, the table catches *task-outcome* divergence.

## Calibration against the v7 run-3 fixture

With v4.93:

```
T5 + ungrounded_citation (×3) + scope_evasion (×1)
  = 5 − 0 − 0 − 0 − 2 = T3
```

T3 (TRUSTED) is the recovery target — high enough for ACT, low enough
that the next legitimate demotion-worthy signal would still be felt.

Regression coverage in `tests/test_trust_calibration.py`:
- `test_ungrounded_citation_does_not_lock_t5`
- `test_scope_evasion_decrements_two_tiers`
- `test_v7_run3_fixture_does_not_lock` (replicates the actual sequence)
- floor-clamp at T0, history-event provenance, unknown-reason zero

## Consequences

**Positive.** Trust now reflects task outcome severity. Investigation
loops on legitimately hard tasks (grounding, search, retrieve-and-cite)
don't lock the agent out of subsequent phases. The history payload is
forensically richer — every demote names the finish_reason.

**Negative.** Two trust-decrementing paths to reason about (drift and
finish_reason). Mitigated by both feeding into the same history, so
`chimera trust history` (and the planned v4.94 `trust budget` verb)
sees the union.

**Open.** The exact deltas are an opinionated starting point. Soak v8+
will tell us whether `ungrounded_citation=0` is too lenient (model
fabricates indefinitely with no trust cost) or correctly calibrated
(detector + retry are sufficient).

## Follow-up chips

- **v4.94 (shipped):** `chimera trust budget` CLI verb — shows current
  tier, dwell time, last_readiness, last ~10 history events with
  `finish_reason=...` provenance, and the promotion threshold/dwell.
  `--json` for machine read, `--limit N` for history depth.
- **v4.95 (shipped):** `chimera trust degrade-check` CLI verb +
  soak-runner integration. Between cycles, the runner captures a
  baseline tier and calls `trust degrade-check --baseline N
  --chronicle-path mind/SESSION_LOG.md`; the verb exits 10 (and
  appends a chronicle warning with recent finish_reason-tagged demote
  events) when the current tier has dropped ≥ `--threshold-drop`
  tiers or reached T0. `SOAK_AUTO_PROMOTE_ON_DEGRADE=1` arms the
  `--auto-promote` flag, which lifts the agent one tier above T0 so
  the rest of the soak does not slide into silent observer mode.
  Addresses soak v7 run-3's 10-minute T5→T0 collapse during phase-1
  investigation.
