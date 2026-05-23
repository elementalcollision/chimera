# ADR 0119 — Sticky detector-finding demotes (v4.119)

**Status:** Accepted (2026-05-23) — defends ADR 0117's commit gate
against ADR 0095's auto-promote rescue loop

## Context

ADR 0117 (v4.117) added a shell-tool guard that blocks `git commit` /
`git push` when trust state is `T0`. The intent: when the cumulative
detector chain (test_claim_invalid, commit_message_diff_drift,
charter_file_count_violation, provenance_claim_invalid, scope_evasion,
etc.) collapses trust to T0, the agent must not be able to commit
again until an operator intervenes.

Soak v20-4th surfaced that the gate never fires in production. The
v20-4th `state/trust_state.json` history shows repeated demote /
promote pairs separated by ~30 seconds:

```
20:52:37  demote T1→T0   reason=finish_reason=commit_message_diff_drift delta=1
20:53:04  promote T0→T1  reason=v4.95 auto-promote-on-degrade: baseline=T5 …
21:01:54  demote T1→T0   reason=finish_reason=commit_message_diff_drift delta=1
21:14:22  promote T0→T1  reason=v4.95 auto-promote-on-degrade: baseline=T5 …
```

v4.95's `auto-promote-on-degrade` (the soak runner invokes
`chimera trust degrade-check --auto-promote` between cycles) was
designed to rescue the agent from drift-score false positives: the
composite readiness score occasionally bounces above the lockdown
threshold without an actual problem, and the rescue puts the agent
back into the loop. That rescue path is correct for score noise. But
the same path also fires when the demote came from a *detector
finding* — i.e. an explicit "the agent did something specific and
wrong" signal. Within ~30 seconds of every T0 demote the agent is
auto-promoted back to T1, well before the next iteration's shell-tool
invocation reads trust state. ADR 0117's gate is invisibly defeated.

## Decision

`chimera trust degrade-check --auto-promote` inspects the most recent
demote event in `TrustState.history` before promoting. Only when that
event's `reason` starts with `drift demote_plan:` does the rescue
fire. Any other reason — `finish_reason=...` (detector finding),
operator-initiated `set_tier(..., kind="operator")`, or
`drift lockdown` — leaves the agent at its current tier until an
operator promotes manually.

### Truth table

| Last demote reason                                | Auto-promote? |
|---------------------------------------------------|---------------|
| `drift demote_plan: composite below threshold`    | **fires**     |
| `finish_reason=commit_message_diff_drift delta=1` | sticky        |
| `finish_reason=test_claim_invalid delta=1`        | sticky        |
| `finish_reason=scope_evasion delta=2`             | sticky        |
| `finish_reason=provenance_claim_invalid delta=1`  | sticky        |
| `operator revoke` (kind=`operator`)               | sticky        |
| `drift lockdown`                                  | sticky        |

The CLI surfaces the skip in `--json` output as
`auto_promote_skipped_reason` and in the chronicle log as
`auto-promote skipped (sticky demote): <reason>` so operators can see
*why* a degraded agent stayed degraded.

### Why the demote reason is the right discriminator

`TrustState.history` already carries the demote source in the
`reason` field — `apply_finish_reason()` formats it as
`finish_reason=<name> delta=<n>`, the drift loop formats it as
`drift demote_plan: <decision-reason>`, operator paths get whatever
the operator passed. No new field is needed and no detector wiring
has to change. The reason prefix is the contract.

## Consequences

* ADR 0117's T0 commit gate becomes load-bearing. Once a detector
  collapses trust to T0, the agent stays there until an operator runs
  `chimera trust promote` (or `set-tier`). Soak v20-3rd's nine
  identical `commit_message_diff_drift` firings would have been one
  firing followed by silence.
* Drift-score rescues still work. False-positive composite-readiness
  bounces continue to auto-recover, preserving the autonomous loop
  for non-malicious noise.
* Operator escape-hatch is unchanged: `chimera trust set-tier T<n>`
  still moves the tier in either direction.

## Non-decisions

* Do NOT change the drift-score demote path. Score-noise rescues are
  why v4.95 exists; this fix narrows v4.95, it does not replace it.
* Do NOT add a stickiness flag to `TrustState`. The history `reason`
  already discriminates demote sources — adding a flag would
  duplicate that information and risk drift between the two.
* Do NOT time out the stickiness. Sticky means sticky until an
  operator promotes. A timer would re-introduce the v20-4th failure
  mode on a longer cadence.
* Do NOT change ADR 0117 (it reads trust state correctly; the bug was
  always that the state never persisted long enough to be read).
* Do NOT modify any detector (`test_claim_invalid`,
  `commit_message_diff_drift`, etc.). The fix lives entirely in the
  rescue path.

## See also

* ADR 0095 — `degrade-check --auto-promote` (the rescue this narrows)
* ADR 0100 — Graduated trust decrements (the demote table this reads
  finish_reasons from)
* ADR 0114 — Autonomous-delivery contract
* ADR 0117 — Trust-state commit gate (the layer this protects)
* ADR 0115 / 0116 / 0118 — Detector chain that drives detector
  demotes
