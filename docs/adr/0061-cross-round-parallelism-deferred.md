# ADR 0061 — Cross-round tool parallelism (v4.40, deferred design)

**Status:** Deferred (2026-05-19)

## Context

[ADR 0040](./0040-parallel-tool-dispatch.md) (v4.18) shipped **intra-round** parallel tool dispatch:
within a single assistant turn that emits multiple `tool_use` blocks,
we fire them all concurrently via `asyncio.gather`. That collapses
the wall-clock of one round from O(sum) tools to O(max).

What's still serial is **the round boundary itself**: the next model
call doesn't start until all tools in the current round have
completed AND we've gotten the next response back. For tasks where
the model walks a long chain (search → fetch → summarise → fetch →
synthesise), the bottleneck is the round-by-round handoff, not the
tool work inside each round.

The user-visible question: can we pipeline rounds so that round
N+1's model call overlaps with round N's slowest tool?

## Why this is genuinely a refactor, not a tweak

The ACT loop today is:

```
for round in range(max_rounds):
    response = await provider.complete_with_tools(messages, ...)
    if no tool_uses: break
    tool_results = await asyncio.gather(*[dispatch(tu) for tu in response.tool_uses])
    messages.append(response, tool_results)
```

Cross-round parallelism means: while `gather(dispatch(...))` is
running, optimistically start the next `complete_with_tools` call
with the tools-pending state. But:

1. **The model needs the tool_results to decide what to do next.**
   Without results, a speculative model call would have to guess.
   That defeats the protocol.
2. **Speculative-then-cancel** is the only honest pattern. Start the
   next round with a placeholder for slow tools; if the real result
   contradicts the prediction, cancel and restart. That's a real
   concurrency control surface, not a one-line refactor.
3. **The provider API doesn't support partial tool_results.** We'd
   have to fake "in-progress" results, which is provider-specific
   and risks the model seeing inconsistent state.
4. **Determinism and replay.** Today an ACT trace is sequential and
   replayable from the api_calls / tool_call_history rows.
   Cross-round pipelining loses that, complicating debugging and
   the v4.20 federation drill's deterministic assertions.

## What we actually want

The interesting workloads — long fetch-and-summarise chains — are
better served by:

1. **Sub-agent fan-out** at the PLAN phase (we already have this:
   `spawn_sub_agent` tool, [ADR 0007](./0007-peer-registry.md)). The model can fork the chain
   itself.
2. **Wider intra-round budgets** that encourage the model to emit
   more parallel tool_uses per round (v4.5 budget knob; could be
   tuned).
3. **Tool result caching** so re-fetches of the same URL across
   rounds are zero-cost (a sub-ADR on its own).
4. **Prefetch** of likely-needed-next inputs based on plan-phase
   intent (research-style speculative fetching; needs design).

These are all attainable without breaking the round boundary
contract. Cross-round speculative execution may eventually be
worthwhile but the ROI vs the four alternatives above is unclear.

## Decision

**Defer.** No code change in v4.40.

The work this ADR replaces:

1. A spec session dedicated to whichever of the four alternatives
   above produces the best wall-clock for our actual research traces
   (likely #1 + #3 in combination).
2. A concrete metric: what's the median round-boundary latency
   today, and where is it dominating? We don't have that data;
   adding it (a `round_boundary_latency_ms` column on `api_calls`
   keyed off the prior round's last tool completion timestamp)
   would let us measure before we optimise.

## Action items

- **Concrete next step:** add `round_boundary_latency_ms` to
  `api_calls` so we know what's actually slow.
- **After data lands:** re-evaluate against the four alternatives
  above.
- **Track separately**: this ADR is the placeholder. Reopen as
  v4.4x when there's data and a chosen direction.

## Non-goals

- No partial-implementation of speculative cross-round execution in
  this slice. That's the trap this ADR exists to avoid.
- No deprecation of the existing intra-round parallel dispatch —
  it's working and remains the durable win from [ADR 0040](./0040-parallel-tool-dispatch.md).
