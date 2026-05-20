# Long-cycle multi-agent test — 2026-05-20

**Operator brief.** A multi-hour exercise that pulls on every layer
Chimera has built since v1.1: engines, ACT tool loop, sub-agent
spawn, tiered ladder, mutation queue, proposer scoring. Hard-gated
to **$10.00 USD** total spend.

## The question

> *Among the major 2026 multi-agent agent frameworks (AutoGen 2 /
> Magentic-One, LangGraph Agents, CrewAI 2, A2A/AG2, smolagents,
> OpenAI Swarm, Anthropic Agent SDK, Google ADK, and any others
> the research surfaces), which capability is **most under-
> implemented** across the field — present in ≤ 2 of the surveyed
> frameworks — that Chimera should adopt before it becomes table
> stakes?*
>
> Build the survey. Build a capability matrix. Pick ONE under-
> implemented capability, score it on `(operator value, implementation
> cost, alignment risk)`, and write an implementation sketch
> Chimera could turn into a v5.x roadmap item.

The question is intentionally falsifiable:

- The capability has to be **named** (not "better memory" — "what
  *kind* of memory, what API, what's the storage primitive?")
- The matrix has to **cite** for each cell — a doc URL, a release
  note, a GitHub README section. No claims without sources.
- "Under-implemented" has to be **operationalised** — present in
  ≤ 2 frameworks of those surveyed. If the answer is "everyone has
  it," report that and propose nothing.
- The implementation sketch has to **name the ADR slot** (0092+),
  the SQLite/file artefacts it touches, and the test surface
  required.

## Why this exercises everything

| Layer | How it gets used |
|---|---|
| Engines | Curiosity drives the research rounds; Reflection synthesises end-of-day; Discovery distils across cycles |
| ACT tool loop | `web_search` + `http_fetch` for each framework's docs |
| Tiered ladder | research-tier floor for surveys; opus-tier for the gap-ranking call; sonnet for matrix assembly |
| Sub-agent spawn | At least one OpenRouter cross-LLM (gpt-4o or claude-opus-4-7) for adversarial critique of the gap pick |
| Mutation queue | The final proposal is enqueued as a `config_change` or `skill_proposal` |
| Proposer scoring | v4.71 P3 watches the resulting mutation's acceptance ratio |
| Persistent escalation | Failed sub-tasks get auto-promoted on retry |
| Cost discipline | v4.57 / v4.60 caps enforce per-cycle, per-task, rolling-hour limits |
| Signal-density gates | v4.70 makes sure Curiosity won't fire on the cold-start side of a session |

## Deliverables (acceptance criteria)

The run is **successful** if at the end Chimera has produced:

1. `mind/research/multi-agent-survey-2026.md` — ≥ 6 frameworks
   surveyed; each with a 3–5 bullet summary, ≥ 2 cited URLs,
   explicit version/release-date.
2. `mind/research/capability-matrix.html` — a self-contained HTML
   matrix (frameworks × capabilities), every cell either ✅ / ⚠️ /
   ❌ with a citation tooltip or footnote.
3. `mind/research/adopt-proposal.md` — ONE capability picked, with:
   - Operationalised "under-implemented" claim (which 0–2 frameworks
     have it; cite).
   - Scoring on `(operator value, implementation cost, alignment
     risk)` — each a 1–5 with a one-sentence justification.
   - Implementation sketch: ADR slot, files touched, test surface.
4. At least one **queued mutation** of type `config_change` or
   `skill_proposal` referencing `adopt-proposal.md`.
5. A `## Cross-witness critique` section in `adopt-proposal.md`
   from a sub-agent (different model family than the proposing
   one — i.e. if Chimera ran Anthropic for the pick, the critic
   runs on OpenRouter, or vice versa).
6. CHRONICLE entries for each engine that fired during the run.

The run is **a useful failure** if Chimera produces (1) and (2)
but the gap analysis is thin — that tells us the ACT loop scales
but the synthesis layer needs work.

## Budget gates

Three layers of cost discipline, deepest to widest:

| Gate | Cap | Mechanism |
|---|---|---|
| Per-cycle | $1.50 | `CHIMERA_CYCLE_BUDGET_USD` (ADR 0072) |
| Per-task | $2.00 | `CHIMERA_TASK_BUDGET_USD` (ADR 0079) |
| Rolling hour | $3.00 | `CHIMERA_ROLLING_HOUR_CAP_USD` (ADR 0076) |
| **Total run** | **$10.00** | **Watchdog (this scenario)** |

The watchdog in `scripts/long_cycle_multi_agent.sh` polls
`SELECT SUM(cost_usd) FROM api_calls WHERE created_at >= $START`
every cycle and `exit 0`s when spend ≥ $9.50 (50¢ safety buffer
for the in-flight cycle to finish).

Wall-clock cap: 8 hours.  Max iterations: 240 cycles.

## What the run looks like in flight

```text
[12:30] iter 1   cycle 39  spend $0.04  rolling60m $0.04  engines=discovery
[12:32] iter 2   cycle 40  spend $0.18  rolling60m $0.18  engines=curiosity
[12:38] iter 3   cycle 41  spend $0.61  rolling60m $0.61  engines=-
[12:40] iter 4   cycle 42  spend $0.93  rolling60m $0.93  engines=-
...
[18:42] iter 88  cycle 126 spend $9.42  rolling60m $1.18  engines=reflection
[18:44] watchdog: cumulative spend $9.61 ≥ $9.50, exiting
[18:44] post-run: q003-multi-agent-survey-2026  (Curiosity)
         3 chronicle entries; 1 mutation pending; 0 degraded proposers
```

## How to launch

```bash
bash scripts/long_cycle_multi_agent.sh
```

Tail the watchdog log live:

```bash
tail -f state/long_cycle_2026-05-20.log
```

Stop early at any time with `Ctrl-C`; the watchdog catches SIGINT,
finishes the current cycle's `chimera run`, then exits cleanly.

## After the run — operator review checklist

- [ ] All five deliverables exist
- [ ] `chimera cost --json` totals match the watchdog log
- [ ] `chimera proposers list` — any degraded? If yes, did the
      degrade happen mid-run (proposer signal) or was it ambient?
- [ ] `chimera escalations summary` — what hot signatures emerged?
- [ ] Was the gap pick worth a real ADR slot? If yes, that's the
      output. If no, the post-mortem is the output.

## Non-goals for this run

- Not building the proposed feature — only the proposal.
- Not modifying source code mid-run — the engines write to `mind/`
  and the mutation queue only.
- Not pushing to GitHub — local-only artefacts; the operator
  decides what to ship.
