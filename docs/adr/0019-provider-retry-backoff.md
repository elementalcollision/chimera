# ADR 0019 — Provider retry/backoff (v3.5)

**Status:** Accepted (2026-05-18)
**Builds on:** [ADR 0001](0001-sdk-chimera.md), [ADR 0018](0018-operational-hardening.md)

## Context

`AnthropicProvider.complete_with_tools` and
`OpenRouterProvider.complete_with_tools` were one-shot calls. Any
transient hiccup (network blip, 503, rate-limit) bubbled straight up to
the ACT executor, surfaced as a tool failure, and burned an api_calls row
even though a single retry would have succeeded.

The ladder system (`HAIKU_LADDER` / `OPUS_LADDER`) handles
permanent-rung failures by escalating, but it shouldn't engage for a
network blip on the trusted rung.

## Decision

New module `chimera/providers/retry.py`:

- `is_transient(exc) -> bool` — classifies httpx + anthropic SDK
  exceptions. Transient: 408, 425, 429, 500, 502, 503, 504, 522, 524;
  `httpx.ConnectError`/`ReadTimeout`/`WriteTimeout`/`ConnectTimeout`/
  `PoolTimeout`/`RemoteProtocolError`/`NetworkError`;
  `anthropic.APIConnectionError`/`APITimeoutError`/`RateLimitError`/
  `InternalServerError`/`APIStatusError` with transient status. Anything
  else (4xx auth/validation, ValueError, generic RuntimeError) is
  permanent.
- `retry_call(fn, *, max_attempts=3, base_delay=0.5, max_delay=30, ...)`
  — runs `fn()` with full-jitter backoff (`backoff*(0.5+rand)`,
  capped at `max_delay`). Logs a WARNING on each retry. Sleep + RNG are
  injectable so tests stay deterministic.

`AnthropicProvider.complete_with_tools` wraps `messages.create` in
`retry_call`. `OpenRouterProvider.complete_with_tools` wraps the entire
httpx round-trip (so transient connect errors retry too).

## Non-goals

- Streaming (`Provider.stream`) is **not** retried. Mid-stream retry is
  much harder (partial output already yielded) and the use cases — ping,
  health check, real-time replies — are short-lived enough that one-shot
  failure is acceptable.
- The ladder is unchanged. Retry runs *within* one rung; escalation is
  still the ladder's job once the rung exhausts its retries.
- No global retry budget. Backoff math (3 attempts, ~0.25–4s total) caps
  worst-case latency without one.

## Tests

`tests/test_provider_retry.py` — 7 cases:
- classifier accepts the documented transient status codes
- classifier rejects permanent codes (401/403/404/400/422/501)
- classifier accepts representative network errors
- classifier rejects unknown exception types
- retry succeeds after one transient failure
- retry gives up after `max_attempts`
- retry does not retry permanent errors

Full suite: 427 passing.
