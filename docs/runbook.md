# Chimera operator runbook

A consolidated guide to running the agent day-to-day. Pairs with the
[README](../README.md) (which is install/setup) and the
[ADR index](./adr/README.md) (which is rationale).

## Three modes you'll actually use

| Mode | Command | When |
|---|---|---|
| One-shot cycle | `uv run chimera run "<task>"` | Hand the agent a discrete task |
| Long-horizon | shell loop over `chimera run` (see below) | Overnight runs / let engines explore |
| HTTP peer | `chimera serve --http` (or `make up`) | Federation with another Chimera |

### Long-horizon driver

The repo doesn't ship a built-in scheduler; use a shell loop:

```bash
set -a; source .env; set +a
# v4.54 (ADR 0073): engines default OFF for long-horizon runs.
# Curiosity/Discovery/Reflection are pure upside in short interactive
# use but compound cost in long-horizon mode — they add tasks faster
# than ACT can verify them, and on the opus tier those exploratory
# tasks compound spend. Operator can opt in if needed:
#   export CHIMERA_ENGINES_ENABLED=1   # only for short runs (seq < 8)
SEQ=${SEQ:-8}
if [ "$SEQ" -ge 8 ] && [ -z "${CHIMERA_ENGINES_ENABLED:-}" ]; then
  export CHIMERA_ENGINES_ENABLED=0
fi
# v4.53 (ADR 0072): per-cycle $ cap — defaults to $2.00 if unset.
export CHIMERA_CYCLE_COST_CAP_USD=${CHIMERA_CYCLE_COST_CAP_USD:-2.00}
# v4.57 (ADR 0076): rolling-60m $ cap — defaults to $20.00 if unset.
# Catches a sequence of cycles each staying just under the per-cycle
# cap. Set to 0 to disable.
export CHIMERA_ROLLING_HOUR_CAP_USD=${CHIMERA_ROLLING_HOUR_CAP_USD:-20.00}
# v4.60 (ADR 0079): per-task $ cap — defaults to $5.00 if unset.
# Stops a single stuck task from being re-promoted across cycles
# each blowing past the per-cycle cap. Set to 0 to disable.
export CHIMERA_TASK_BUDGET_USD=${CHIMERA_TASK_BUDGET_USD:-5.00}

for i in $(seq 1 "$SEQ"); do
  echo "=== cycle $i @ $(date +%H:%M:%S) ==="
  uv run chimera run 2>&1 | tee -a /tmp/chimera-longrun.log | tail -12
  # Exit early when INBOX is clear.
  if ! grep -qE "^\s*-\s*\[\s\]" mind/INBOX.md; then
    echo "INBOX clear — stopping at cycle $i"; break
  fi
done
```

The agent learns across cycles via the v4.46 task-escalation memory:
a task that fails at haiku on cycle N auto-promotes to sonnet on
cycle N+1, and gets a larger round budget too (v4.47). The
[ADR 0072](./adr/0072-cost-runaway-guards.md) per-cycle $ cap stops
the loop if a single cycle's spend exceeds `CHIMERA_CYCLE_COST_CAP_USD`
(default $2.00).

## What the dashboard tells you

`http://127.0.0.1:3000` after `npm run dev` in `control-plane/`.

| Widget | What it tells you | When to react |
|---|---|---|
| Status | Cycle, trust tier, drift composite | drift > 0.30 → plan demotion imminent |
| Token cost / Cost over time | Spend per model | Sudden spike → check ladder routing |
| Cost rate (15m) | Rolling $/min with band (green/amber/red) | RED → kill the run; AMBER → review what's running |
| Drift composite | Per-cycle sparkline | Trending up → drift detectors firing |
| Phase timings | Per-phase wall-clock | act dominates → tool calls heavy |
| Ontology / Audit | KFM entity counts; stale + dead | dead > 0 → entities never touched |
| Mutations / Queue health | Pending proposals + recurrence | High recurrence → same suggestion firing repeatedly |
| Re-anchor history | K-operator demotions over time | Trending up → plan instability |
| Tool fan-out | Parallel batch rate + cost/tool-call | < 25% parallel → model isn't fanning out |
| Model utilization | API calls per model + boundary p50/p95 | Peak > 100/cycle → one model thrashing |
| Skill graph / Assembly | Dynamic skills + dependencies | New nodes → mutation auto-applied |
| Peers / Trust / Emergence | Federation state | Any REFUSE → check peer health |
| Fragmentation | Compound-task failures | New row → consider task-text rewrite |
| Inbox / Chronicle | Current tasks + narrative | Always |

Refresh every 30s if the auto-refresh toggle is on (Tweaks panel).

## Common operator chores

### Approve a queued mutation

```bash
chimera mutations list                  # see what's pending
chimera mutations show <id>             # inspect payload
chimera mutations approve <id>          # mark approved
chimera skills assemble <id>            # for skill_proposal types: actually activate
```

### Archive stale entities (manual)

```bash
chimera ontology --audit                # see stale + dead counts
chimera ontology --archive-stale        # promotes long-DEPRECATED → ARCHIVED
                                        # (auto runs each housekeeping; this is on-demand)
```

### Permanently kill long-archived entities (gated)

```bash
chimera ontology --propose-kills        # queues kill_entity mutations
chimera mutations list                  # operator reviews
chimera mutations approve <id>          # per-row approval
chimera ontology --apply-kills          # ARCHIVED → KILLED via K-operator
```

### Inspect what the agent has learned

```bash
chimera escalations list                # recent task failures + tier used
chimera escalations summary             # which signatures have failed at which tiers
chimera escalations clear --grep foo    # forget specific learning
```

### Preview a task split

```bash
chimera split "Research and write the FOUR sections, each with citations..."
chimera split "<long task text>" --no-model       # heuristic only
chimera split "<long task text>" --json
```

Heuristic detects multi-section / multi-deliverable / fanout shapes;
a sonnet-tier provider (deepseek-v4-pro post-v4.53) proposes
independent sub-tasks. The verb does NOT auto-rewrite INBOX —
operator decides whether to apply by manually editing `mind/INBOX.md`
(mark original `[-]`, append sub-tasks as `[ ]`).

Use this before a long-horizon run when a task signature keeps
showing up in `chimera escalations summary` under ⚠️ HOT SIGNATURES.

### Search the wiki

```bash
chimera search "datacentre water"        # text output
chimera search "datacent*"               # prefix matching
chimera search '"quick brown fox"'       # exact phrase
chimera search "agonistic OR datacenter" --json
chimera search "anything" --rebuild      # force index refresh first
```

FTS5 over `mind/wiki/`. Index refreshes each cycle via housekeeping
(mtime-gated; unchanged files cost nothing). Disable with
`CHIMERA_AUTO_WIKI_INDEX_DISABLED=1`.

The agent uses the same index via the `mind_search` tool — it
should try `mind_search` before `web_search` for any question
the agent might already know about itself.

### Pre-flight: estimate cost before a long-horizon run

```bash
chimera estimate                    # text projection with per-task breakdown
chimera estimate --json             # structured payload
chimera estimate --tier sonnet      # override default starting tier
```

Anchored to api_calls history when available, tier-typical token
estimates otherwise. Flags tasks whose per-cycle projection exceeds
the cycle cap (they'll trip on every cycle), and totals exceeding
the rolling-hour cap. Honest heuristic — use the prior_failures
column in the JSON output to find tasks worth rewriting before
running.

### Inspect cost from the CLI

```bash
chimera cost                       # text report with band + warnings
chimera cost --json                # structured payload for scripts
chimera cost --cycle 17 --json     # spend on a specific historical cycle
```

Pipe into shell guards:

```bash
band=$(chimera cost --json | jq -r .band)
if [ "$band" = "red" ]; then
  echo "Cost rate red — stopping"
  exit 1
fi
```

### Verify providers + state

```bash
chimera doctor                          # config preflight
chimera ping --provider both            # one-token reply from each
```

### Refresh the graph manually

As of v4.62 (ADR 0081) the Kuzu graph projection is **opt-in**.
Default = off; housekeeping skips the auto-refresh entirely. The
SQLite-recursive-CTE path covers ~95% of dashboard queries. To
opt in:

```bash
export CHIMERA_GRAPH_ENABLED=1          # auto-refresh in housekeeping
```

The CLI verbs are always available regardless of the gate:

```bash
chimera graph rebuild                   # full clear + rebuild (~0.21s)
chimera graph rebuild --incremental     # diff-only
chimera graph query "MATCH (e:Entity) RETURN count(e)"
chimera graph stress --entities 500     # synthetic load benchmark
```

Without `CHIMERA_GRAPH_ENABLED=1`, a hand-built graph goes stale
the next cycle — the CLI prints a hint to that effect when you
init or rebuild.

### Federation drills (sanity checks)

```bash
chimera scenario federation_drill           # spawn peer, identity + KFM + witness call
chimera scenario federation_trust_drill     # REFUSE → DEGRADE → ALLOW via trust ladder
chimera scenario federation_http_drill      # HTTP transport with bearer auth
```

## When things look wrong

| Symptom | First check |
|---|---|
| Dashboard shows "INBOX has no tasks" but file has lines | dashboard storage version + Reset button |
| ACT keeps hitting max_rounds on the cheap tier | `chimera escalations list` — v4.46 should be auto-promoting |
| Sub-agent calls fail silently | check `is_error=True` tool_results in the cycle log; v4.49 should be raising structured errors |
| Container won't start with `serve --http` on 0.0.0.0 | v4.52 guard — set `CHIMERA_PEER_TOKEN` in `.env` |
| Tool dispatch errors flood the log | model emitting wrong arg shape; v4.41 hint should be feeding back — read the next round's tool_result |
| Graph rebuild takes forever | use `--incremental` (v4.31); for full perf history see [ADR 0045](./adr/0045-graph-rebuild-perf.md) |
| Mutation queue growing fast | `chimera mutations health` — duplicates get absorbed in-place via recurrence_count (v4.19) |
| Fingerprint write errors on macOS | Kuzu single-file DB; sidecar fix is in v4.43 — verify [ADR 0069](./adr/0069-round-boundary-instrumentation.md) note about file-vs-directory |

## Writing tasks for the agent

v4.56 ([ADR 0075](./adr/0075-task-conventions-and-tier-floor.md)).
The 2026-05-19 escalation postmortem (`mind/overnight/escalation-postmortem.md`)
identified two task-shape anti-patterns that consistently burn rounds:

- **"Pick two modules from chimera/core/"** forces filesystem
  discovery before the real work. **Name the modules explicitly.**
- **"Research and write four sections each with citations"** is
  four parallel tasks bundled as one. **Split them, or accept that
  haiku will hit `max_rounds` and v4.46 escalation memory will spend
  the next cycle on sonnet.** The agent now auto-floors research-
  shaped task text at the sonnet tier (keyword detection in
  `chimera.core.escalation.research_task_floor_tier`), but splitting
  is still the right pattern for parallel-section research.

If a task signature accumulates ≥ 2 failures, `chimera escalations
summary` will surface it under `⚠️ HOT SIGNATURES` (v4.54 / ADR 0073).
That's the signal that the **task text** needs rewriting, not just
the tier.

## Cost discipline

- `chimera tiers --json` mirrors current model prices into `state/tiers.json`
  so the dashboard's cost math stays accurate.
- The v4.46 escalation memory paired with v4.47 tier-aware budgets
  means the agent *should* spend more on hard tasks and less on easy
  ones. Watch the **Model utilization** widget's peak/cycle column —
  if a cheap model is hitting peak 100+ on the same task signature
  repeatedly, the escalation memory may need clearing or the task
  text rewriting.

## Emergency stops

- **Kill the engines but keep the loop**: `CHIMERA_ENGINES_ENABLED=0
  uv run chimera run`. The Opus PLAN call and all three engines stay
  silent; ACT still runs.
- **Refuse new outbound peer calls**: set the peer in the registry's
  trust state to T0 — the v2.5 `PeerAwareDispatcher` will REFUSE.
- **Lock down trust**: `chimera trust lockdown` — drops to T0
  immediately.
- **Stop the container**: `make down`.

## Where the durable state lives

| Path | What |
|---|---|
| `state/chimera.db` | SQLite — entities, transitions, mutations, api_calls, activity log, escalations |
| `state/chimera.graph` | Kuzu single-file graph projection (auto-incremental in housekeeping) |
| `state/drift_log.jsonl` | Per-cycle drift composite (read by dashboard sparkline) |
| `state/fragmentation_log.jsonl` | Compound-task failures (v4.5) |
| `state/protocol_journal/<peer>.jsonl` | Peer schema observations |
| `state/peer_trust_journal/<peer>.jsonl` | Peer trust decisions (ALLOW/DEGRADE/REFUSE) |
| `state/trust_state.json` | This agent's current trust tier + readiness |
| `state/tiers.json` | Snapshotted model prices (auto-synced via `chimera tiers --json`) |
| `mind/INBOX.md` | Open tasks — the ASSESS phase reads these |
| `mind/HEARTBEAT.md` | Live cycle state |
| `mind/CHRONICLE.md` | Narrative log — engines write here |
| `mind/wiki/*.md` | Long-form knowledge — graph WikiDoc projection sources from here |
| `~/.chimera/peers/<agent_id>.json` | Peer registry entries |


## Output-token budget (ACT loop)

The ACT executor caps each model turn's output via `max_tokens`. Before
v4.71 this was a flat **2048** for every tier — small enough that
`claude-opus-4-7` repeatedly hit `finish_reason="length"` mid-tool_use,
silently truncating reasoning and corrupting downstream rounds (nine
`length` finishes observed across cycles 25–28, including a fresh one
in cycle 27).

Current per-tier defaults (set in `chimera/core/act.py` →
`ActExecutor._TIER_MAX_TOKENS`):

| Tier   | Default `max_tokens` | Model output ceiling (Anthropic published) |
|--------|----------------------|---------------------------------------------|
| haiku  | 4 096                | ~8 192 (claude-haiku-4-5)                   |
| sonnet | 8 192                | ~8 192 standard / ~64 k extended thinking   |
| opus   | 16 384               | ~32 000 (claude-opus-4-7)                   |

All three sit comfortably below the provider ceiling so a single budget
clip never costs us a whole tool_use turn, while keeping per-call cost
bounded (opus output is $75/Mtok — a 16 k ceiling is ~$1.20 worst-case
per turn, vs the ~$0.15 worst-case under the old 2048 cap).

### Overriding the cap

Two environment variables, checked in this order:

1. `CHIMERA_ACT_MAX_TOKENS_<TIER>` — per-tier override, e.g.
   `CHIMERA_ACT_MAX_TOKENS_OPUS=24576`.
2. `CHIMERA_ACT_MAX_TOKENS` — global override applied to every tier.

Programmatic callers can still pass `max_tokens=<int>` to
`ActExecutor(...)` explicitly; that wins over both env vars.

### When to raise it further

- Persistent `length` finishes after this change → bump the affected
  tier's env var by 1.5×–2× and watch the **Model utilization** widget
  for cost impact.
- If opus is being used for long-form code generation (assembly /
  cross-critique), consider `CHIMERA_ACT_MAX_TOKENS_OPUS=24576`
  (still under the 32 k API ceiling).
- Never raise above the provider's published output ceiling — the API
  will reject the request outright.

### How to confirm it's working

The cycle-history meta records each call's `finish_reason`. After
raising the budget, the rolling tally in subsequent cycle prologues
(the `by_finish=[length=N, ...]` line) should show `length` plateauing
or shrinking — not growing. If `length` keeps appearing on the same
tier, raise that tier's env override as described above.

```bash
# Inspect the api_calls table for finish-reason trends:
sqlite3 state/chimera.db \
  "SELECT model_id, finish_reason, COUNT(*) FROM api_calls \
   GROUP BY model_id, finish_reason ORDER BY 3 DESC;"
```

