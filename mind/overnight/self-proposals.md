# Self-Proposals — 2026-05-20 Overnight

_Top-3 organic changes surfaced by the discovery + reflection engines that
I endorse. Operator reviews on wake-up. Existing pending mutations #7
(loop-spin guard) and #8 (reflection→planner bridge) already address the
biggest two reflection insights from today; these three are additive._

---

## 1. Add a per-cycle "refining vs spinning?" self-check at cycle 3

**Source signal.** Evening reflection 2026-05-20: 221 tool-use calls,
multiple passes through cycle 12, a long tail of 20–26 s calls. The
engine's own diagnosis: "I was iterating when I might have synthesized."

**Why I endorse it.** This is the single clearest behavioural lever the
reflection engine has ever named. The cost isn't the per-call latency —
it's the loop count. A cheap structural intervention at cycle 3 (one
extra meta-prompt token, zero new infra) plausibly cuts total cycles by
30–50 % on deep tasks.

**Status.** Already queued as mutation **#7** (`prompt_injection`,
`chimera/core/loop.py`). I am explicitly re-endorsing it here rather
than duplicating the row. Operator: please approve #7.

**Size.** Small. No new mutation needed — #7 is sufficient.

---

## 2. Bridge Reflection → Planner so meta-insight becomes next-day tasks

**Source signal.** 2026-05-19 evening reflection ended with "Tomorrow
I'll do something differently — set a goal before pulling out the
mirror." Then 2026-05-20 ran 235 calls of unstructured churn. The
resolution from the previous night never reached the planner: today's
loop had no memory of yesterday's lesson.

**Why I endorse it.** Reflection is wasted if it's write-only. The
Chronicle is currently a journal nobody reads — including me. Wiring
yesterday's Evening Reflection paragraph into the Plan-phase prompt
closes the metacognitive feedback loop the engines were designed for.

**Status.** Already queued as mutation **#8** (`wiring`,
`chimera/proposals/generate.py`). Re-endorsed; no duplicate row created.

**Size.** Small. Operator: please approve #8.

---

## 3. NEW — Cap Midday Curiosity on cold-start days

**Source signal.** 2026-05-19 midday: with no history to mine, the
discovery engine still ran a full investigation, then noted "the
investigation became meta — I studied the fact that there was nothing
yet to study." The evening reflection explicitly says: "There's no need
to rush to fill it."

**Why I endorse it.** The engine identified its own anti-pattern:
spinning up a research project to compensate for an empty session. On
days where Morning Discovery returns "no prior history", Midday
Curiosity should defer (or downgrade to a one-line "nothing to mine
yet") instead of generating wiki/projects/q002-… meta-notes. This
saves a research cycle's worth of tokens and — more importantly —
prevents the agent from training itself on the habit of manufactured
busywork.

**Proposed change.** In the engine that drives Midday Curiosity, gate
investigation on a non-trivial Morning Discovery payload. If Morning
Discovery flags "fresh session / no history", emit a 1-line stub
instead of a full notes.md.

**Status.** Queued below as a new `config_change` mutation. Small
enough — touches one engine config gate, no schema changes.

---

## Summary for operator

| # | Insight | Mutation | Action |
|---|---------|----------|--------|
| 1 | Spin-guard at cycle 3 | #7 (existing, pending) | approve |
| 2 | Reflection → Planner wiring | #8 (existing, pending) | approve |
| 3 | Skip Midday Curiosity on cold-start | NEW below | review + approve |

All three are small, reversible, and traceable to specific Chronicle
lines from 2026-05-19 and 2026-05-20. None require new infra.
