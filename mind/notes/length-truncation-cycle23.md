# Cycle 23 — `claude-opus-4-7` length-truncation post-mortem

Source data: `state/chimera.db` (`api_calls`, `agent_activity_log`,
`ladder_outcomes`, `mutations`, `task_escalations`), `mind/INBOX.md`,
`mind/SESSION_LOG.md`, `docs/runbook.md`.

## TL;DR

Cycle 23 issued **18 sequential `claude-opus-4-7` turns** in a single
ACT loop. The **18th turn (api_calls.id=690)** terminated with
`finish_reason="length"`, having emitted **exactly 2048 output tokens**
— the flat per-turn `max_tokens` cap that was in force prior to v4.71.
The truncation is **not a one-off**: 21 of the 28 length-finishes in
the entire DB are opus calls clipped at exactly 2048, one per cycle
from 19→24 and then accelerating to 3/cycle from 25→29. The cycle 23
event is a representative member of that family, not an isolated
anomaly.

The truncated output content itself is **not recoverable** — `api_calls`
stores metrics only (cycle / provider / model_id / token counts /
finish_reason / latency / tool_uses_count / timestamps). There is no
prompt or response body in the schema. What can be reconstructed is
the *context* in which the clip happened, which is what this note
records.

## The offending call

From `api_calls` filtered on `cycle=23`:

| id  | input_tok | output_tok | latency_ms | finish_reason | tool_uses | created_at           |
|-----|-----------|------------|------------|---------------|-----------|----------------------|
| 673 | 3 403     | 111        | 2 418      | tool_use      | 1         | 05:32:56Z            |
| 674 | 3 561     | 92         | 2 164      | tool_use      | 1         | 05:32:58Z            |
| 675 | 3 708     | 87         | 2 086      | tool_use      | 1         | 05:33:00Z            |
| 676 | 3 917     | 77         | 1 950      | tool_use      | 1         | 05:33:02Z            |
| 677 | 7 166     | 115        | 2 859      | tool_use      | 1         | 05:33:05Z            |
| 678 | 7 404     | 75         | 2 417      | tool_use      | 1         | 05:33:07Z            |
| 679 | 7 554     | 77         | 1 964      | tool_use      | 1         | 05:33:09Z            |
| 680 | 7 687     | 76         | 2 009      | tool_use      | 1         | 05:33:11Z            |
| 681 | 7 839     | 75         | 2 340      | tool_use      | 1         | 05:33:14Z            |
| 682 | 7 961     | 79         | 2 170      | tool_use      | 1         | 05:33:16Z            |
| 683 | 8 133     | 279        | 3 779      | tool_use      | 1         | 05:33:20Z            |
| 684 | 8 859     | 158        | 3 724      | tool_use      | 1         | 05:33:23Z            |
| 685 | 17 684    | 132        | 4 655      | tool_use      | 1         | 05:33:28Z            |
| 686 | 22 379    | 227        | 5 261      | tool_use      | 1         | 05:33:33Z            |
| 687 | 23 924    | 106        | 2 412      | tool_use      | 1         | 05:33:36Z            |
| 688 | 24 492    | 82         | 2 466      | tool_use      | 1         | 05:33:38Z            |
| 689 | 27 737    | 279        | 4 906      | tool_use      | 1         | 05:33:43Z            |
| **690** | **28 101** | **2 048** | **25 949** | **length** | **4** | **05:34:09Z** |

Pattern visible in the table:

1. Input tokens grow monotonically (3.4k → 28.1k) as tool_results are
   appended to the conversation. The model's working context for the
   final turn was ~28k input tokens.
2. Output tokens stayed under 280 for every prior turn — those were
   single-tool-call think-and-dispatch turns. The 18th turn was
   different: it emitted **4 tool_uses** alongside its text and ran
   for 25.9s (vs ~2-5s for every prior turn). That is the signature
   of a synthesis/summarisation turn where the model was trying to
   consolidate findings *and* fan out remaining work, and the 2048
   cap clipped the consolidation.

## What cycle 23 was working on

`agent_activity_log` for cycle 23 shows the canonical ASSESS → PLAN
(skipped, no engine) → WAKE → ACT (`{"tasks": 1, "completed": 0,
"api_calls": 18}`) → COMMIT → FLUSH → ROTATE → WRITE sequence. ACT
ran one task across 18 API calls and **completed=0** — i.e. the
length-clip on call #690 prevented the task from being marked done.

The cycle 23 ACT window (05:32:53 → 05:34:09) coincides with the
inbox's largest-by-far task: *"Research and write the FOUR missing
analytical sections the cross-witness critique flagged in
`mind/agonistic_futures_annotated.md`"* — a compound research task
demanding inline citations, sub-agent adversarial review, and a
references block. That task survived to be re-attempted in
subsequent cycles; it is now marked `[x]` in `mind/INBOX.md`.

`task_escalations` is **empty for cycle 23**, which means the failure
mode was not "tier ran out of rounds" — it was a within-turn token
clip that the ladder did not register as escalation-worthy.
`ladder_outcomes` records all 18 calls as `outcome="success"`,
**including the clipped one** — the ladder's success classifier
does not currently treat `finish_reason="length"` as a failure
signal. That is itself a latent bug (see Recommendations).

## Truncation context (the content we *can* recover)

Output content is not persisted. The closest proxy is the downstream
artifact: `mind/agonistic_futures_annotated.md` was eventually
completed across cycles 23–28 (the task is now `[x]` in INBOX), with
the `## Missing sections (researched additions)`, `## References`,
and `## Section-by-section sub-agent reviews` headings present. So
the *reasoning* the clip damaged was eventually re-issued — but only
because the task survived multiple cycles. A single-cycle task with
the same shape would have silently shipped a half-finished artifact.

## Pattern across cycles

```
cycle 19: 1  length-clip   (claude-opus-4-7, 2048)
cycle 20: 1                (claude-opus-4-7, 2048)
cycle 21: 1                (claude-opus-4-7, 2048)
cycle 22: 1                (claude-opus-4-7, 2048)
cycle 23: 1                (claude-opus-4-7, 2048)  ← this report
cycle 24: 1                (claude-opus-4-7, 2048)
cycle 25: 3                (claude-opus-4-7, 2048 ×3)
cycle 26: 3                (claude-opus-4-7, 2048 ×3)
cycle 27: 3                (claude-opus-4-7, 2048 ×3)
cycle 28: 3                (claude-opus-4-7, 2048 ×3)
cycle 29: 3                (claude-opus-4-7, 2048 ×3)
cycle 30: 1                (claude-opus-4-7, 4096)   ← cap was raised here
```

Cycle 30's single clip is at **4096**, confirming the runbook's
v4.71 change landed (`_TIER_MAX_TOKENS` per-tier defaults in
`chimera/core/act.py`, runbook §Output-token budget). But cycle 30
still hit the new ceiling once, on a 26.9k-input-token turn — i.e.
the underlying behaviour (opus emitting >4k output tokens on
synthesis turns) is **real**, not an artefact of the old cap.

Overall: 28/1024 calls clipped = **2.73%** total truncation rate;
21/28 of those are opus@2048; the remaining 7 split between
deepseek-v4-pro (6) and the one opus@4096.

## Why this happened

1. **Flat 2048 max_tokens for every tier** (pre-v4.71). Opus's
   published output ceiling is ~32k. 2048 sits at the lower end of a
   single tool_use turn's natural output for a synthesis call.
2. **Long ACT loops on compound research tasks**. The 18-turn ACT
   loop in cycle 23 is normal for the agonistic-futures task family;
   each successive turn adds tool_result text, growing input from
   3.4k → 28.1k. By turn 18 the model wants to summarise — i.e.
   exactly the case where output >2048 is likely.
3. **No alarm on `finish_reason="length"`**. `ladder_outcomes`
   classifies the call `success`. The dashboard has no
   length-truncation widget (per `docs/runbook.md` "What the
   dashboard tells you"). The only signal the operator saw was the
   per-cycle `by_finish=[length=9,…]` printout in the system header
   on cycle 27, which is what triggered the inbox tasks.

## Recommendations / status

- [x] **Raise per-tier max_tokens** — done in v4.71
  (`docs/runbook.md` §Output-token budget; haiku=4096, sonnet=8192,
  opus=16384). The inbox task that drove this is checked off.
- [ ] **Length-truncation alarm** — inbox already carries
  `mind/notes/length-alarm-spec.md` as an open task. This report's
  data (2.73% truncation rate over 1024 calls; cycle 30 still
  clipping at 4096) is the empirical justification for that spec.
- [ ] **Treat `finish_reason="length"` as a ladder failure**.
  Currently `ladder_outcomes` records these as `success`. They are
  *not* successes — the tool_use was clipped. A one-line change in
  the ladder's outcome classifier would unblock the v4.46
  escalation memory from learning around them.
- [ ] **Persist prompt/response payloads (optionally, sampled)** for
  truncated calls. Right now this post-mortem cannot show the actual
  clipped content because `api_calls` is metrics-only. A debug ring
  buffer keyed on `finish_reason="length"` would make future
  truncation reports self-contained.

## What is *not* in this report

- The actual truncated text from call id=690. Not stored anywhere on
  disk; the conversation transcript is held in-process only and
  flushed at cycle end.
- A reconstruction of the specific tool_use arguments the model
  intended to emit on turn 18. `tool_uses_count=4` is the only
  surviving signal.
