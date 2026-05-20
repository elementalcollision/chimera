# ADR 0040 — Parallel tool dispatch in ACT (v4.18)

**Status:** Accepted (2026-05-19)

## Context

The Anthropic API (and OpenRouter equivalents) emits multiple
`tool_use` blocks inside a single assistant turn when the model wants
to call several tools concurrently — e.g. `web_fetch(url_a)` and
`web_fetch(url_b)` in one shot, or `web_search` + `code_exec` to
prepare a follow-up. Our ACT executor was iterating those blocks
serially:

```python
for tu in response.tool_uses:
    output = await self._dispatcher.dispatch(tu.name, args, ctx)
```

That throws away the latency win the model was reaching for. With
network-bound tools (web_fetch, mcp_client.peer_call, subagent
spawns), the wall-clock cost of an ACT round was O(sum) of every
tool, not O(max).

Autoresearch fundamentals call for the agent to dynamically expand
its tool calling under a wide budget. Parallelism is the cheapest
correct way to do that.

## Decision

Dispatch the batch of `tool_uses` from one assistant turn through
`asyncio.gather`, preserving result order against tool_use_id.

### Implementation

- `chimera/core/act.py` — replaced the serial dispatch loop with an
  inner `_run_one` coroutine and `asyncio.gather`.
- Each call still goes through `Dispatcher.dispatch`, so the full
  policy pipeline (global deny → context deny → context allow →
  requires_env → availability) runs per-call.
- `detect_degenerate_loop` now sees the entire batch appended to
  history *before* any dispatch fires — same semantics, slightly
  earlier abort.
- A single log line records the parallel fan-out so we can correlate
  it with cost rows later.

### Safety

- The dispatcher has no shared mutable state per call. The shell
  tool is read-only. code_exec runs in a sandboxed subprocess.
  web_fetch / web_search are independent HTTP clients. mcp_client
  uses per-call connections. subagent spawns its own provider
  session. No tool today shares state across calls in a way that a
  serial-vs-concurrent ordering would change.
- Tool result truncation is per-call (`max_result_size_chars`),
  unchanged.
- Errors are still caught per-call and turned into `is_error=True`
  tool_result blocks — one failing tool no longer blocks the others.

## Tests

- `tests/test_act.py::test_act_dispatches_multiple_tool_uses_in_parallel`
  registers a `slow_probe` tool that sleeps 150ms and records
  start/end timestamps. The test asserts both calls overlap
  (`max(starts) < min(ends)`) and that total elapsed is < 280ms
  (serial would be ≥ 300ms).
- Full pytest: 503 passing, 5 skipped (previously 502, +1 new).

## Non-goals

- **Cross-round parallelism.** The model still gates each round; we
  only parallelize within a single assistant turn.
- **Bounded concurrency.** The model typically emits ≤ 4 tool_uses
  per turn. If a future model exceeds that, we can wrap the gather
  in a semaphore — not needed today.
- **Tool-side rate-limiting.** Provider-level rate limits on
  web_fetch / subagent are still each tool's responsibility.
