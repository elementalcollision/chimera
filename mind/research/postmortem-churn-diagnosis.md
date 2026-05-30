# Postmortem-writing churn — diagnosis + instrumentation (pre-next-soak close-out)

**Date**: 2026-05-30
**Observed in**: every R3 build soak's postmortem phase (v41 capstone noted it;
v42, v43, v44 all showed it). Pattern: the BUILD is near-one-shot clean, then
the postmortem task churns — `artifact_missing` ×N → `skipped_three_strikes`
×M — before the postmortem finally lands. The churn is wasteful (cycles +
cost) but self-recovering (the postmortem does eventually land).

Representative (v44 re-run, 16 ACT records): `3 artifact_missing`,
`8 skipped_three_strikes`, `4 stop`. The build cycles were clean; the churn was
all in the postmortem-writing task.

## The mechanism (read from the code, not the trace)

`chimera/core/act.py` `_execute_inner`, the no-more-tools / stop branch:

```python
if not response.tool_uses or response.stop_reason in ("stop", "length"):
    completed = response.stop_reason == "stop"
    if completed:
        expected = expected_artifacts(task_text)   # parses the .md path
        missing  = check_artifacts(expected)        # exists? non-empty?
        if missing:
            completed = False
            finish_reason = "artifact_missing"
```

So `artifact_missing` fires when the model **stops** (believes it is done) but
the expected postmortem `.md` is missing or zero-byte. Three consecutive
failures trip the three-strikes auto-skip (`SKIPPED_THREE_STRIKES`), and the
loop's watchdogs keep it alive until a later cycle actually writes the file.

## Leading hypotheses (to confirm on the next soak)

1. **"Claims done without writing."** The agent's final turn is text-only
   ("I've written the postmortem…") but it never issued the write tool call
   that cycle — so the file is absent and `artifact_missing` fires. The
   postmortem is the most narrative deliverable, so this failure mode (assert
   completion in prose) is most likely here.
2. **Wrong path.** The agent writes a postmortem but to a path that doesn't
   match `expected_artifacts(task_text)` (e.g. a slightly different name), so
   the gate sees the expected path missing.
3. **Length truncation.** The postmortem is the longest deliverable (full
   template + iteration table + READY block); the model may hit `stop_reason
   == "length"` mid-write across rounds, landing a partial or no file on some
   cycles.

These are distinguishable from the *ledger* once it records WHICH artifact was
missing — which it did not, until this chip.

## The instrumentation (this chip)

The soak ledger recorded `finish_reason: "artifact_missing"` but **not which
artifact** was missing — so a post-hoc analysis (the v44 worktrees are pruned;
that forensic is gone) could only see the *count* of churn cycles, never the
cause. `build_act_record` now surfaces the `ActResult`'s already-populated
detail:

- `missing_artifacts`: the expected paths that were missing/empty when
  `artifact_missing` fired.
- `incomplete_artifacts`: `[path, marker-msg]` pairs when `artifact_incomplete`
  fired (the file exists but lacks a required marker, e.g. the READY block).

On the next soak, `jq -r '[.cycle,.finish_reason,(.missing_artifacts|join(","))]
| @tsv' act-tools.jsonl` will show, per churn cycle, exactly which artifact and
why — confirming hypothesis 1/2/3 directly instead of by speculation.

## Why instrument rather than fix now

The fix differs sharply by hypothesis: (1) needs a "you described writing X but
issued no write tool-call this cycle" nudge in the task/INBOX or a detector;
(2) needs path-normalization in `expected_artifacts`/the INBOX; (3) needs a
chunked-write instruction or a larger response budget for the postmortem task.
Committing to one fix without the per-cycle artifact detail would be guessing.
This chip makes the next soak self-diagnosing; the fix follows from its ledger.

## Next

- Land this instrumentation, then on the next R3 soak read the per-churn-cycle
  `missing_artifacts` and pick the matching fix (one of the three above).
- Not blocking: the churn is wasteful but self-recovering (post-#168 it no
  longer deadlocks convergence).
