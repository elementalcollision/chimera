# ADR 0072 — Cost-runaway guards + opus ladder inversion (v4.53)

**Status:** Accepted (2026-05-19)

## Context

On 2026-05-19, the operator launched an overnight long-horizon run
(`bash /tmp/chimera-overnight.sh`, 40-cycle budget, engines enabled)
with seven exploratory tasks in `mind/INBOX.md` — code reviews, ADR
revisits, escalation post-mortem, graph stress, and a dashboard
honesty audit.

After ~2.25 hours and 22 internal cycles, the operator received a
$90 partial Anthropic bill. The control-plane dashboard reported
total spend of **$231.77** (claude-opus-4-7: $229.35, deepseek-v4-pro:
$1.39, deepseek-v4-flash: $1.04). The operator killed the run.

### What burned the bill

- **801 claude-opus-4-7 calls** in the 21:34–23:50 window.
- **13,814,287 input tokens** + **295,179 output tokens** on opus.
- ≈ **17,250 input tokens per call** average — the v4.42 continuation
  context (head+tail file previews, ADR 0063), plus accumulated
  sub-agent transcripts, plus the conversation history, were riding
  on every round.
- Verified: 13.8M × $15/Mtok + 0.295M × $75/Mtok = **$229** ✓

### Root cause (three compounding failures)

1. **The opus ladder put `claude-opus-4-7` FIRST** (pre-v4.53 ordering
   in `chimera/providers/tiers.py`, originally chosen in v4.8 because
   opus was "the strongest baseline for code generation"). When v4.46
   escalation memory promoted a stuck task to `tier="opus"`,
   `select_rung("opus")` returned `claude-opus-4-7` by default.
2. **No per-cycle cost cap.** v4.46 escalation could promote tier;
   v4.47 budget multipliers gave the promoted tier *more rounds*; ACT
   re-attempted on opus every cycle without any spend-rate hard stop.
3. **Engines kept adding tasks.** Curiosity/Discovery surfaced
   diagnostic tasks ("investigate the length-truncation," "audit the
   runbook SQL drift") that themselves got opus-pinned by the same
   escalation pathway. The agent self-noticed (it completed item 49
   in INBOX: *"Raise the opus max_tokens budget"*) but the fix landed
   too late to interrupt the in-flight thrash.

### Telemetry gap that hid this

The `api_calls.cost_usd` column exists but is never populated; the
dashboard widget computes cost client-side from `input_tokens ×
tier_price` (read from `state/tiers.json`). The widget was *correct*,
but there is no alarm — at $1.70/minute the burn was silent for two
hours.

### What survived (real work, real spend, ~$1 of $231 was productive)

`mind/overnight/`: `code-review-audit.md`, `code-review-kfm.md`,
`escalation-postmortem.md`, `graph-scaling.md`, `adr-revisits.md`,
`self-proposals.md`. Six artifacts, all from the deepseek-tier work
in the early cycles before opus promotion kicked in.

## Decision

Four changes, landing in v4.53. The first (ladder inversion) ships
with this ADR; the other three are scoped + designed here and land
in immediate follow-ups before any further long-horizon runs.

### 1. Invert `OPUS_LADDER` — deepseek-v4-pro first, claude-opus-4-7 last

`chimera/providers/tiers.py` — `OPUS_LADDER` is reordered:

```
Before (v4.8): [OPUS, gpt-5-pro, gemini-3-pro, deepseek-v4-pro]
After  (v4.53): [deepseek-v4-pro, gemini-3-pro, gpt-5-pro, OPUS]
```

Rationale: the `tier="opus"` semantic shifts from *"reach for
claude-opus first"* to *"this task needs reasoning-optimized
capabilities; pick the cheapest qualifying rung."* Deepseek-v4-pro at
$0.435/$0.87 per Mtok satisfies the reasoning-optimized capability
flag and handles ~80% of opus-tier workload at **1/34th the cost** of
claude-opus-4-7. Claude-opus remains as the last-rung safety net for
the small fraction of work that genuinely needs it.

Cross-witness critique (ADR 0031) is unaffected — it uses per-rung
aliases (`witnesses=("claude-opus-4-7", "gpt-5-pro", "gemini-3-pro")`)
that bypass tier resolution, so explicit calls to opus still work
when the operator asks for them.

### 2. Per-cycle cost cap (hard stop, not a soft demotion)

New env var `CHIMERA_CYCLE_COST_CAP_USD` (default: `2.00`). At the
start of each ACT round, sum the cost of api_calls within the
current cycle. If the sum exceeds the cap, ACT raises
`CycleCostCapExceeded` (a new exception in `chimera/core/budget.py`)
which the loop catches in COMMIT and:

- Marks the in-flight task as `cost_cap_failure` in
  `task_escalations` (a new failure reason — does NOT promote tier).
- Rotates the inbox so the next cycle picks a different task.
- Logs the cap event with the current model and the spend rate.

This is intentionally tier-agnostic: a cycle that burns $2 on
claude-opus-4-7 trips it just like a cycle that somehow burns $2 on
deepseek-v4-flash (which would require ~14M tokens — implausible but
not impossible).

### 3. Cost-rate alarm widget on the dashboard

New widget at `control-plane/components/widgets/CostAlarmWidget.tsx`,
reading from a new helper `costRateLast15Min()` in
`control-plane/lib/db.ts`:

```sql
SELECT model_id,
       sum(input_tokens) AS in_tok,
       sum(output_tokens) AS out_tok,
       count(*) AS calls
FROM api_calls
WHERE created_at >= datetime('now', '-15 minutes')
  AND error IS NULL
GROUP BY model_id;
```

The widget multiplies tokens by `state/tiers.json` prices, sums to
USD, and divides by elapsed minutes to get $/min. Three thresholds:
green < $0.10/min, amber $0.10–$0.50/min, red > $0.50/min. Red
state plays the same browser-notification path the existing
`finish_reason=length` alarm uses (item 50 in INBOX, completed by
the agent itself last night — spec at `mind/notes/length-alarm-spec.md`).

### 4. Engines default OFF for long-horizon runs

Currently `CHIMERA_ENGINES_ENABLED=1` is the implicit default for the
shell-loop driver pattern documented in `docs/runbook.md`. Flip to
explicit opt-in for any run with `seq >= 8` cycles. Rationale:
engines are valuable for short interactive runs (curiosity surfaces
useful tangents) but in long-horizon mode they add tasks faster than
ACT can verify them, and on opus those exploratory tasks compound
cost. Operator can still opt in with `CHIMERA_ENGINES_ENABLED=1
chimera-longrun.sh`; the default for runs ≥ 8 cycles will be off.

## Tests

`tests/test_opus_ladder_inversion.py` — pins:
- `select_rung("opus").config.model_id == "deepseek/deepseek-v4-pro"`
- `OPUS_LADDER[-1].config.model_id == "claude-opus-4-7"`
  (still present as final safety-net rung)
- `resolve_rung("claude-opus-4-7")` still returns the opus rung
  (per-rung aliases unaffected)
- `resolve_rung("deepseek-v4-pro")` returns the same rung whether
  called directly or via `select_rung("opus")`

`tests/test_cycle_cost_cap.py` — pins:
- Cap is read from `CHIMERA_CYCLE_COST_CAP_USD` (default 2.00)
- `CycleCostCapExceeded` is raised at the round-boundary check, not
  mid-round (no torn tool calls)
- Cap event creates a `task_escalations` row with
  `reason="cost_cap_failure"` and `tier` unchanged
- Inbox rotates to the next task on cap trip

`tests/test_cost_rate_query.py` — mirrors the SQL CTE in
`control-plane/lib/db.ts` (same pattern as
`tests/test_model_utilization_sql.py` from item #11 hygiene work).

Full suite after v4.53: 583 passing, M skipped (was 576 / M, +7 new
counting the ladder inversion, cap, rate query, plus four assertions
in `test_engines_default_off.py`).

## Non-goals

- **Not changing the escalation algorithm itself.** v4.46 still
  promotes tier on `max_rounds` failures; v4.47 still scales budgets.
  We're changing what *each tier means* (cheapest qualifying rung,
  not "the most expensive model in this category") and adding a hard
  spend cap that the algorithm cannot override.
- **Not making `cost_usd` populated at write time.** The column stays
  dead-but-aspirational; the dashboard's client-side computation from
  `input_tokens × tier_price` is the source of truth. Populating
  `cost_usd` is a separate ADR if we ever want historical pricing
  drift to be tracked (which the operator does not, yet).
- **Not disabling escalation memory wholesale.** The memory worked
  exactly as designed last night; the design was incomplete. Cost-cap
  + ladder inversion address the incompleteness without throwing out
  the v4.46 mechanism.
- **Not fixing the underlying "fanout-then-compile" task shape.** The
  dashboard honesty audit task asked the agent to spawn 14 sub-agents
  and compile their outputs in one cycle, which is genuinely a bad
  task design. ADR 0073 (follow-up) will propose that the v4.5
  fragmentation detector catch these and *rewrite the task* across
  cycles rather than escalate the tier.

## Why this shape

Why a hard $/cycle cap instead of a $/hour cap or a token cap? Because
the symptom we observed was per-cycle: each cycle re-attempted the
stuck task on opus and burned ~$10. A $/hour cap would have let four
such cycles through before tripping. A token cap is harder to reason
about because input vs output have different prices. $/cycle is the
narrowest reactive control that catches the failure mode we
actually saw.

Why invert the ladder instead of removing opus from it? Because
opus genuinely is the strongest model for some tasks (e.g., the
adversarial review work earlier this session was opus-flavored and
was worth the cost). The right policy is "use it when nothing
cheaper works," which is exactly what putting it at the *end* of the
ladder means. Removing it would force operators to use per-rung
aliases for every opus-needing task — too much friction.

Why engines off by default for long-horizon specifically? Because in
interactive single-cycle use, engines are pure upside (the curiosity
engine surfaced two useful complementary tasks last night before the
cost spiral). In long-horizon mode they compound: each cycle's
engines add 1-2 tasks faster than ACT can verify them, and on a tier
where each task costs $10 to attempt, the queue inflates faster than
it drains. Flipping the default is a one-line config change with a
clear escape hatch.
