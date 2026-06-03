# Trust-progression validation (2026-06-02)

**Question (self-PR follow-up):** does the trust ladder advance T0→T4 from
*accumulated gate-approved commits*, so self-PR eligibility (T4, ADR 0163) is
*earned* by a demonstrated track record of faithful, gate-accepted work?

**Answer: No — and that's a gap.** Trust progression exists and auto-promotes,
but on **operational health**, not on the critic-gate track record.

## What actually drives promotion

`ChimeraLoop._maybe_autopromote` (loop.py:945) computes readiness each cycle from
three signals, then calls `TrustManager.maybe_autopromote`:

```
readiness =  stability_weight · (1 − drift_score)        # drift detector
           + activity_weight  · activity_rate            # api_calls / 6 over last 3 cycles
           + hygiene_weight   · (1 − failure_rate)        # ERRORED api_calls / total
```
(weights 0.4 / 0.3 / 0.3; promotion_threshold 0.70; `TrustManager.readiness`,
manager.py:258.)

- **stability** = inverse drift.
- **activity** = how many API calls recently (i.e. *is it doing things*).
- **hygiene** = inverse *API-call error* rate — NOT gate rejections.

None of these is "did the agent land gate-approved, faithful commits." A run that
is active, low-drift, and free of API errors promotes — even with zero
gate-approved commits. So **T4 (and thus self-PR eligibility) can be reached
without ever passing the in-loop critic gate on real work.**

## Why it matters

ADR 0163 gates the autonomous self-PR at T4 precisely to require *earned*
autonomy. But T4 is earned from generic operational signals, not from the
agent's gate record. The trust threshold and the safety gate are decoupled: the
thing that proves faithfulness (gate-approved commits, ADR 0162) does not feed
the thing that unlocks proposing PRs (trust tier).

## Proposed enhancement (next chip — has an operator judgment call)

Add a fourth readiness signal: **gate-approval rate** — the fraction of recent
in-loop critic-gate decisions that were `allowed:true` (from
`critic-gate-log.jsonl`), so trust progression reflects a demonstrated history of
faithful, gate-accepted commits. Open question for the operator: the **weight**
(how much should gate-record count vs. stability/activity/hygiene?) and whether a
*minimum* count of gate-approved commits should be a hard precondition for T4
(not just a weighted contribution).

Backward-compat: default the new signal to neutral when no gate history exists,
so existing readiness behavior and tests are unchanged until the loop feeds it.
