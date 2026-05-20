# Engine telemetry post-mortem — 2026-05-20

**Subject:** Discovery / Curiosity / Reflection engines (v1.1, ADR 0003 §"Reggio loop")
**Asked by:** operator, after the v4.51 engine-telemetry widget shipped and the
v4.53–v4.68 cost-discipline + observability arc landed.
**Scope:** Are the engines doing what they were built for? What should change?

> Self-critical assessment from Chimera, anchored in live data from
> `state/chimera.db` (38 cycles, 1,371 api_calls, six chronicle
> entries across two operator sessions). Operator decides what to
> act on; this artifact is the assessment, not the plan.

---

## TL;DR

Three honest findings, three corollary improvements.

1. **The engines barely run, and they don't tell the operator how
   often.** Across 38 cycles I have exactly ONE ladger-recorded
   engine firing (reflection at cycle 13). `last_runs.json` shows
   two days of activity. `mind/CHRONICLE.md` shows six entries.
   That's three sources of truth disagreeing about how many times
   the engines ran. → **Unified engine telemetry** is the missing
   primitive.
2. **The Reggio daily rhythm doesn't fit the operator's session
   shape.** Discovery runs at 08:00 UTC, Curiosity at 14:00 UTC,
   Reflection at 22:00 UTC, each at most once per UTC day. But the
   2026-05-19 / 2026-05-20 sessions had ~135-minute and ~37-minute
   bursts, not all-day rhythms. The engines either run once or
   not at all per session. → **Signal-density gating** should
   replace clock-based gating, building on the cold-start fix
   (mutation #13).
3. **Proposer engines have low signal-to-noise.** The mutation
   queue shows skill_proposal 4-failed / 1-applied / 3-pending —
   62.5% noise rate. config_change 60% approval rate. The engines
   propose more than they propose well. → **Proposer outcome
   scoring** should feed back into engine selection: an engine
   below 50% acceptance over 10+ proposals gets demoted.

Below: the data, the architecture critique, and the three concrete
proposals with non-goals.

---

## 1. Telemetry — the foundations don't account for themselves

### Data

```
=== ladder_outcomes by task_type ===
  (null)               success            n=1348
  plan                 success            n=9
  skill_assembly       success            n=8
  skill_critique       success            n=3
  skill_critique       retry_exhausted    n=2
  reflection           success            n=1   ← only engine in the ledger
```

```
=== engines that actually wrote to CHRONICLE.md ===
  2026-05-19  Morning Discovery     (DiscoveryEngine)
  2026-05-19  Midday Curiosity      (CuriosityEngine)
  2026-05-19  Evening Reflection    (ReflectionEngine)
  2026-05-20  Evening Reflection    (ReflectionEngine)
```

```
=== state/engines/last_runs.json ===
{
  "curiosity":  "2026-05-19",
  "reflection": "2026-05-20"
  // DISCOVERY MISSING
}
```

### What this means

`DiscoveryEngine.run()` writes to CHRONICLE.md via
`ChronicleManager.upsert_section()` and records an `api_calls` row
+ a `ladder_outcomes` row with `task_type="discovery"`. The
chronicle entry for 2026-05-19 proves it ran successfully. But:

- The ledger doesn't have a `task_type="discovery"` row.
- `last_runs.json` doesn't have a `discovery` key.

So either (a) the loop never called `scheduler.mark_ran('discovery')`
after the firing, or (b) the chronicle entry was written by a
different code path. Either way, **three independent stores
disagree**. An operator looking at the agent's recent introspective
behaviour has to read three sources and reconcile by hand.

The v4.51 engine-telemetry widget ([ADR 0070](docs/adr/0070-model-utilization-widget.md))
counts api_calls per model — which conflates engines with ACT
calls on the same model. There is no widget, no table, no helper
that answers the question *"did the engines run today, and how
useful were they?"*.

### Why this matters

The whole point of the engines (per the Reggio thesis) is to give
the agent a metacognitive layer that the operator can inspect. If
the operator can't tell whether the layer is firing, the layer
might as well not exist. The 2026-05-20 evening reflection wrote:

> Tomorrow I'll watch for that pattern earlier — when I hit the
> third pass on the same problem shape, I'll pause and ask
> whether I'm refining or just spinning.

That's a valuable insight. It's also invisible from the dashboard
unless the operator opens `mind/CHRONICLE.md` directly. The engine
output isn't tied to the cycles it influenced.

---

## 2. Time-window gating doesn't fit operator sessions

### Data

The 2026-05-19 session lasted ~135 minutes (21:34 PDT → 23:50 PDT
= roughly 04:34 → 06:50 UTC the next day). All three engines fired
in that window because the chronicle has a 2026-05-19 entry from
each — but the scheduler's windows say Discovery should fire only
between 08:00–13:59 UTC. **A 135-minute session that didn't
overlap any of the three windows got engines firing anyway.**

Likely explanation: the operator's first cycle hit BEFORE the
scheduler had a `last_runs.json` for that day, so the
`_window_contains` check picked whichever engine corresponded to
the current UTC hour, AND the scheduler's per-day idempotency
allowed exactly one firing of each. The Reggio "morning /
midday / evening" rhythm collapses to "first 60-90s of each
session, at most three times."

### What this means

The scheduler is doing two things that interact poorly:

1. **Time-window selection** — `pick_due()` picks an engine based
   on UTC hour. The intent is "discovery at morning, curiosity at
   midday, reflection at evening."
2. **Per-day idempotency** — each engine fires at most once per UTC
   day. The intent is to prevent expensive repeated firings.

In an operator-session model (short bursts, often at irregular
hours), the time-window gating contributes nothing — the operator's
session covers whatever UTC slice happens to be active. The
idempotency does the actual work of "fire once per day," which
could be implemented without any time-of-day logic.

The 2026-05-19 *evening reflection* from CHRONICLE captured this
gap explicitly:

> The midday investigation became meta: I studied the fact that
> there was nothing yet to study. […] Tomorrow I'll do something
> differently — I'll let the first real task, however small,
> emerge before I start analyzing my own reflection.

That's the agent observing its own anti-pattern. The cold-start
curiosity gate (mutation #13, approved 2026-05-19 23:50 PDT)
addresses the symptom. The architecture allowing it persists.

---

## 3. Proposers produce more than they propose well

### Data

```
=== mutation status by type ===
  config_change   approved  3
  config_change   rejected  2     → 60% approval
  skill_proposal  applied   1
  skill_proposal  failed    4     → 1-of-8 = 12.5% applied
  skill_proposal  pending   3
```

The three approved `config_change` mutations (engine-proposed
self-improvements from the 2026-05-19 overnight) WERE solid:
loop-spin guard (#7), reflection→planner wiring (#8), cold-start
curiosity gate (#13). The two rejected ones presumably weren't.

But `skill_proposal`: **four failed assemblies and one applied.**
The validation pipeline (v4.6 / ADR 0024) catches the failures
before they pollute the runtime, so this isn't dangerous — but
it's expensive in tokens (each failed skill_proposal cost a
sonnet-tier assembly cycle plus a critique loop) and in operator
attention (each one shows up in the queue for triage).

### What this means

The engines that propose are working off heuristics — chronicle
patterns, drift signals, escalation memory — and those heuristics
are noisy. A 12.5%-applied rate on skill_proposals means the
operator is doing 87.5% of the filtering work. The engines aren't
learning from their rejection history; they propose with the same
priors regardless of whether their last 8 proposals were accepted.

There IS a `recurrence_count` mechanism on mutations (v4.19) that
absorbs duplicates by bumping a counter rather than creating new
rows. But that protects against duplicate signal, not low-quality
signal.

---

## Architectural critique: where the foundations show their seams

Four structural observations beyond the data:

### A. The engines have no view of "what is this cycle for?"

Engines run in PLAN, BEFORE ACT picks a task from INBOX. Discovery
distills the last 5 cycles; it doesn't know what the next 1 cycle
intends. Curiosity picks a seed topic from the chronicle, not from
the in-flight task. Reflection summarises after the fact.

The result is engines that drift on chronicle content rather than
serving the operator's actual session goal. The 2026-05-19 Midday
Curiosity famously investigated "fresh session initiation; no
prior history" — a literally empty topic. The engine fired
because the slot existed, not because there was anything to
investigate.

### B. Engines record api_calls but the loop doesn't tag them as engine-derived

`record_api_call(...)` in `discovery.py` and `reflection.py` passes
the same fields as ACT — there's no `phase="engine_discovery"` or
`engine_name=...` column. So when the cost-per-model widget (ADR
0033) shows 394 deepseek-v4-flash calls, the operator can't tell
how many were engines vs. ACT-on-cheap-tier. The v4.60 task_signature
column was the precedent for adding scope — engines need the same
treatment.

### C. The kill-switch is binary, all-or-nothing

`CHIMERA_ENGINES_ENABLED=0` (ADR 0034) disables all three engines.
There's no way to keep Reflection on while turning Discovery off,
or to make Curiosity opt-in for active research sessions only.
The most useful engine on any given day might be the one the
operator can't selectively keep.

### D. The chronicle is write-only knowledge

Engines write to `mind/CHRONICLE.md` but never read from it
across days. Each Morning Discovery has no memory of yesterday's
Evening Reflection unless the prompt injects it explicitly
(mutation #8 added this, but it only applies to Plan-phase, not
to the engines themselves). Five days from now, today's Evening
Reflection insight will be just as buried as it would be in a
markdown file the agent never opens.

The v4.61 FTS5 search (ADR 0080) gives the agent the *capability*
to read its own chronicle. Nothing yet uses it.

---

## Proposed improvements (operator decides which to act on)

Five proposals, ranked by my honest sense of leverage. Each names
the foundation it changes and how confident I am that the
intervention helps.

### P1. Unified engine telemetry table — **HIGH leverage, LOW risk**

Add `engine_runs` table to the SQLite schema:

```sql
CREATE TABLE IF NOT EXISTS engine_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    engine          TEXT NOT NULL,          -- discovery|curiosity|reflection
    cycle           INTEGER NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,          -- success|skipped|failed
    skip_reason     TEXT,
    api_calls       INTEGER DEFAULT 0,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    cost_usd        REAL,
    chronicle_added INTEGER DEFAULT 0,      -- lines appended
    mutations_proposed INTEGER DEFAULT 0,
    summary         TEXT                    -- 200-char excerpt
);
```

Each engine writes one row per firing. Deprecate
`last_runs.json` and the `task_type` field on `ladder_outcomes`
for engines specifically; they become legacy with fall-backs.

Dashboard widget reads from `engine_runs` directly: "engines
last 7 days: D=3 C=2 R=5; total spend $0.18; chronicle lines
added 412." One table, one source of truth.

**Confidence: HIGH.** This is pure plumbing. The current
inconsistency is the canonical wrong; this fixes it.

### P2. Signal-density gating — **HIGH leverage, MEDIUM risk**

Replace UTC time windows with substantive-content gates. Each
engine declares a `should_fire(db, cycle) -> bool` predicate:

- **Discovery**: fires iff the last N cycles contain ≥ K api_calls
  AND/OR ≥ M activity_log rows that touched entities. On
  cold-start days, returns False.
- **Curiosity**: fires iff Discovery wrote something substantive
  today AND no curiosity has fired in the current operator
  session. (Already partially implemented via mutation #13's
  cold-start gate.)
- **Reflection**: fires iff today's cycle count ≥ K (default 5),
  i.e. there's something to reflect on.

Keep per-UTC-day idempotency as a SAFETY net but stop using it as
the primary gate.

**Confidence: MEDIUM-HIGH.** The exact thresholds are guesses;
they should be operator-tunable. But the direction is right: fire
when there's signal, not when the clock says so.

### P3. Engine acceptance-rate scoring → demotion — **MEDIUM leverage, LOW risk**

Track per-engine `proposal_acceptance_rate` as
`(approved+applied) / (approved+applied+rejected)` over the last
N proposals (default 10). When the rate falls below 50%, the
engine gets a `degraded` flag. Degraded engines:

- Still fire and still write to chronicle
- Do NOT propose new mutations
- Surface a warning in the dashboard ("Curiosity is in
  degraded mode: 3/10 proposals accepted")

Operator can promote back by `chimera engines promote curiosity`
after rewriting the proposer prompt or thresholds.

**Confidence: MEDIUM.** This adds policy where there isn't any
yet. The 50% threshold is a guess and might need tuning. But the
direction is honest — proposer quality should self-correct.

### P4. Tag engine api_calls with engine_name — **LOW effort, HIGH clarity**

Add a `caller` column (or reuse `task_signature` from v4.60) to
mark which engine made each api_call. Cost-per-model widget gets
an engine breakdown for free; cost_runaway_drill can synthesise
engine cost separately from ACT cost.

**Confidence: HIGH.** One column, one ALTER TABLE, four callers
to update. The data lets every other proposal here become
data-driven instead of vibes-driven.

### P5. Engine selective enable + chronicle-as-input — **MEDIUM leverage, HIGH risk**

Replace `CHIMERA_ENGINES_ENABLED` with per-engine flags
(`CHIMERA_DISCOVERY_ENABLED=1` etc.), all default off post-v4.54
([ADR 0073](../../docs/adr/0073-observability-tightening.md) §4
already shipped the global default-off; this just makes the
opt-in granular). AND wire the engines to read the chronicle via
the v4.61 FTS5 index — Reflection should search for yesterday's
"I'll watch for that pattern" and check whether it actually
manifested today.

**Confidence: MEDIUM.** The selective enable is mechanical and
safe. The chronicle-as-input requires engine prompt rewrites,
which is where engine quality regressions often hide. Worth
prototyping behind a feature flag; should not ship as default-on
until the acceptance-rate scoring (P3) is in place to catch a
regression.

---

## Non-improvements I considered and rejected

- **Replacing the engines with a single "introspection" call** —
  attractive in theory (one prompt, one model call, one chronicle
  entry per cycle) but loses the deliberate split between
  *distillation* (Discovery), *exploration* (Curiosity), and
  *reflection* (Reflection). The three lenses produce different
  outputs from the same data; collapsing them produces averaged
  bland output.
- **Letting the engines call ACT recursively** — would give them
  tool access (web_search, code_exec) but blows up the ACT cost
  cap surface ten different ways. The v4.53–v4.60 cost discipline
  was designed for tasks, not engines. Out of scope until the
  per-engine token cap (a P3 follow-up) is in place.
- **Adding more engines** (Critique, Synthesis, …) — the existing
  three aren't carrying their weight; adding more without first
  fixing telemetry and acceptance-rate scoring would just spread
  the noise wider.

---

## What this post-mortem doesn't fix

Honest acknowledgements of limits:

- I'm assessing engine value over 38 cycles across two operator
  sessions. That's a small sample. The conclusions hold for the
  data I have but may not generalise.
- The chronicle entries I quoted were written *by these engines*.
  Their own evaluation of their own usefulness has obvious bias.
  An external evaluator (a sub-agent on a different provider, or
  the operator) would produce a more independent read.
- The proposed `engine_runs` table doesn't backfill — pre-v4.69
  firings stay invisible. We accept that and start fresh.

---

## Operator action items

If the operator wants to act on this post-mortem in the same
pattern as ADRs 0072–0087:

1. **P1 (engine_runs table)** — green-light to implement. Pure
   plumbing, additive migration. Probably v4.69 + ADR 0088.
2. **P4 (caller column on api_calls)** — green-light to implement
   alongside P1. Same migration, same dashboard plumbing.
3. **P2 (signal-density gating)** — discuss thresholds first.
   Likely v4.70 + ADR 0089.
4. **P3 (acceptance-rate demotion)** — discuss the 50% threshold
   first. v4.71 + ADR 0090.
5. **P5 (chronicle-as-input + selective enable)** — defer until
   P1+P3+P4 land. The improvements compound; trying P5 without
   the others is the same architecture mistake repeated.

— Chimera, 2026-05-20
