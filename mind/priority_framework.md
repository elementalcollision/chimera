# Chimera Priority Framework

**Purpose:** Consistent task triage, model-tier assignment, and resource allocation across all agents and sub-agents.
**Scope:** All tasks entering the inbox, sub-agent briefs, peer requests, and internal engine proposals.
**Design principles:** Cost-aware, latency-sensitive, preemptible, auditable.

---

## 1. Priority Levels

| Level | Label | Meaning | SLA | Preemptible by | Example |
|-------|-------|---------|-----|----------------|---------|
| P0 | **Critical** | System integrity threat; active drift; operator interrupt. | Respond within 1 cycle | Nothing | Drift composite >= lockdown threshold; graph fragmentation; security alert |
| P1 | **High** | External user request; time-sensitive deliverable; dependency for >=2 other tasks. | Complete within 5 cycles | Only P0 | "Search X and synthesize by EOD"; peer request with deadline |
| P2 | **Normal** | Standard research, analysis, artifact creation. | Best effort; revisit within 20 cycles | P0, P1 | "Write a summary of Y"; sub-agent critique task |
| P3 | **Low** | Curiosity, exploration, self-improvement, backlog grooming. | When no higher task exists | All above | "Investigate Z if idle"; engine proposals; ADR revisits |

**Default assignment:** Incoming tasks are P2 unless explicitly tagged or the urgency classifier (see §3) scores them higher.

---

## 2. Resource Allocation Matrix

Priority determines **model tier**, **token budget**, and **tool-use allowance**.

| Priority | Recommended tier | Max input tokens | Max output tokens | Max tool calls | Sub-agent allowed? | Retry strategy |
|----------|-----------------|------------------|-------------------|----------------|-------------------|----------------|
| P0 | opus | 100% of context | >=8K (set max_tokens) | Unlimited | Yes, on sonnet+ | Immediate retry (1 cycle) on failure |
| P1 | sonnet | 75% of context | 4K | 30 | Yes, on haiku+ | Retry once; escalate to P0 if still fails |
| P2 | sonnet or haiku | 50% of context | 2K | 15 | Only on haiku | Retry once at user's discretion |
| P3 | haiku | 30% of context | 1K | 5 | No | No retry; log and defer |

**Tier selection heuristics:**
- *haiku* -> cheap lookup, summarisation, formatting, sub-agent execution for well-scoped subtasks.
- *sonnet* -> default analytical work, synthesis, research with moderate depth.
- *opus* -> adversarial review, high-stakes planning, code generation with correctness requirements, drift investigation.

**Cost weighting** (from `state/tiers.json`):
- haiku: $0.14-0.80/M input / $0.28-4.00/M output
- sonnet: $0.40-3.00/M input / $0.87-15.00/M output
- opus: $0.44-15.00/M input / $0.87-75.00/M output
- Prioritise deepseek-v4 within each tier for cost efficiency; reserve claude-opus for cases requiring adversarial reasoning.

---

## 3. Dynamic Priority Classifier

On inbox insertion, run this lightweight scoring to override the default P2:

```
priority_score =
  + 3.0  IF task mentions user/human/operator explicitly
  + 2.0  IF task references an existing failed artifact (fragmentation_log)
  + 2.0  IF task has a time constraint ("by", "before", "EOD", "urgent")
  + 1.5  IF task is a dependency for another open task
  + 1.0  IF task requires external information (web_search, http_fetch)
  + 0.5  IF task is self-improvement / engine-proposed
  - 1.0  IF task is curiosity-only with no artifact requirement
```

| Score range | Assigned priority |
|-------------|-------------------|
| >= 6.0 | P0 |
| 3.0 - 5.9 | P1 |
| 1.0 - 2.9 | P2 |
| < 1.0 | P3 |

The classifier result is recorded alongside the task so priority assignment is auditable.

---

## 4. Preemption Rules

When a higher-priority task arrives mid-cycle:

1. **Current task preemption:** If the current task is P2 or P3 and a P0 or P1 arrives, the current task is **parked** -- its intermediate state is captured in `state/parked_task_<id>.json` and its tool-allowance checkpoints logged.
2. **Parked-task recovery:** When the preempting task completes, the parked task is restored at the top of the inbox with its original priority + a 1-cycle "warmup" bonus (score +0.5).
3. **P0 never preempted:** Only operator kill can interrupt a P0.
4. **P1 preempted only by P0:** P1 tasks run to completion unless a P0 arrives.
5. **Flood control:** If >=3 P0 tasks arrive within 10 cycles, an automatic rotation fires -- the system considers whether it's in a runaway loop and logs a SYNTHESIS_RECOMMEND entry.

---

## 5. Escalation Path

| Situation | Action | New priority |
|-----------|--------|-------------|
| P2 task fails >=2 times | Escalate to P1; re-evaluate task-text for clarity | P1 |
| P1 task fails >=2 times | Escalate to P0; flag as fragmentation risk | P0 |
| Task consumes >2x its budgeted tool calls | Log to escalation memory; prompt task-text rewrite | +1 level |
| Sub-agent returns length finish (truncation) | Escalate to parent's tier+1; raise max_tokens | Parent +1 level |
| Peer request unanswered for >5 cycles | Escalate via inter-agent channel | P1 |

---

## 6. Integration with Existing Systems

| System | Integration point |
|--------|------------------|
| **Trust/tier** (T0-T5) | Priority is per-task; trust tier is per-agent. A T1 agent cannot run P0 tasks even if assigned. The framework respects trust as a ceiling. |
| **Drift detection** | A drift composite >= lockdown threshold auto-assigns P0 to the diagnostic task, preempting all else. |
| **Fragmentation log** | Tasks whose artifact IDs appear in fragmentation_log.jsonl get +2.0 in the priority classifier. |
| **Phase timing** | The ACT phase respects priority when multiplexing -- P0 tasks bypass the round-robin and run first. |
| **Sub-agent spawn** | A sub-agent inherits the parent task's priority for its brief. Sub-agents cannot self-promote. |
| **Inbox rotation** | Before each rotate action, the inbox sorts by priority (descending), then by age (ascending). Old P2 tasks age into P1 after 30 cycles of neglect (see §7). |

---

## 7. Priority Aging

Tasks that sit untouched for extended periods automatically rise in priority to prevent starvation:

| Time in inbox | Priority bump |
|---------------|--------------|
| >= 10 cycles | +0.5 to classifier score |
| >= 20 cycles | +1.0 to classifier score (minimum P2) |
| >= 30 cycles | P1 floor; logged as "stale task" in CHRONICLE |
| >= 50 cycles | Escalate to operator via HEARTBEAT.md |

This ensures low-priority tasks don't languish indefinitely.

---

## 8. Auditing

Every priority assignment, preemption, escalation, and aging event is logged to `state/priority_events.jsonl`:

```
{"ts": "...", "task_id": "inbox-42", "event": "assign", "priority": "P1", "score": 4.5, "reason": "user request + time constraint"}
{"ts": "...", "task_id": "inbox-7", "event": "preempt", "by": "inbox-42", "from_priority": "P2", "to_priority": "P1_parked"}
{"ts": "...", "task_id": "inbox-7", "event": "recover", "from": "P1_parked", "to": "P2"}
{"ts": "...", "task_id": "inbox-19", "event": "escalate", "from": "P2", "to": "P1", "reason": "failed 2x"}
{"ts": "...", "task_id": "inbox-12", "event": "age", "cycles": 30, "new_floor": "P1"}
```

A `priority_events.jsonl` viewer/aggregator can be added as a dashboard widget in a future cycle.

---

## 9. Implementation Checklist

- [ ] Wire priority classifier into inbox insertion (inbox.py or equivalent).
- [ ] Store priority field on each inbox task row.
- [ ] Add preemption logic to the ACT phase scheduler.
- [ ] Write parked-task state persistence.
- [ ] Add escalation path to task-failure handlers.
- [ ] Log all priority events to state/priority_events.jsonl.
- [ ] Add aging sweep to the rotate/housekeeping phase.
- [ ] Update runbook with priority framework decision tree.
