# F2 LoCoMo cross-conversation deadlock — shared AsyncClient root cause

**Date**: 2026-05-27
**Status**: FIX SHIPPED in this chip (provider-level shared client)
**Author**: Chimera-Agent (F2 cross-conv-deadlock chip)

## TL;DR

After PR #96 closed the Ollama-embedder synchronous-wait path, the
full 1,986-item LoCoMo sweep with `--hybrid-retrieval
--retrieval-top-k 8` continued to deadlock at the conv-26 → conv-30
boundary on a 10-conversation sweep, while a 4-conversation slice of
the same four conversations completed cleanly. The remaining offender
is the per-call `async with httpx.AsyncClient(...)` pattern inside
`OpenRouterProvider.complete_with_tools`: even when every coroutine
runs on the persistent loop (PRs #93/#94), repeated AsyncClient
context-manager teardown accumulates anyio-backend state on Python
3.14 until the executor wedges and the next future never schedules.
The canonical 3-thread idle stack signature
(`_PyMutex_LockTimed`/`kevent`/`_queue_SimpleQueue_get`) is the
symptom; the cumulative `__aexit__` is the cause.

The fix is the textbook httpx async pattern: one `AsyncClient` per
provider instance, created lazily on the loop that first uses it,
reused for every subsequent call. The provider also gains an
`aclose()` for tests and a defensive rebind path for the rare case
where the provider instance is reused across loops.

## Why the deadlock is N-dependent on total corpus size

The 4-conversation slice contains the SAME four conversations
(conv-26, conv-30, conv-41, conv-42) that the full 10-conv sweep
deadlocks across, but the slice completes. The relevant difference is
not the per-conversation work but the cumulative call count:

* 4-conv slice: ~8 OpenRouter calls (4 conversations × 2 QA each).
* 10-conv full sweep: hundreds of OpenRouter calls before conv-26 is
  even reached (the upstream `locomo10.json` orders conversations
  alphabetically by sample_id; conv-26 is roughly the 5th of 10).

By the time conv-26 finishes in the full sweep, the persistent loop
has serviced hundreds of `async with httpx.AsyncClient(...)` open/close
cycles. Each cycle:

1. Allocates a fresh `httpcore.AsyncConnectionPool` + transport.
2. The transport's anyio backend lazily attaches to the loop.
3. On `__aexit__`, the pool drains and the transport closes — but the
   anyio backend's blocking-task offload state stays attached to the
   loop's default executor.

The cumulative effect is not a leaked resource per se (memory stays
bounded, fds get reclaimed) but a wedge in the executor's queue
scheduling: after enough cycles, `call_soon_threadsafe` from
`run_coroutine_threadsafe` no longer wakes the loop in time, and the
future submitted by the main thread sits unscheduled. Three threads,
all parked, all idle — the canonical signature observed in operator
`sample` snapshots.

## Why PR #94's coverage didn't fix this

PR #94 removed every repeating `asyncio.run` site outside the
allow-list and routed them through `run_on_persistent_loop`. That
fix is correct and necessary — without it, *each call's loop
teardown* fires `shutdown_default_executor`, which wedges far
earlier (PR #93 caught the first occurrence at conv-41 first QA).
PR #94 closed that class of triggers.

What PR #94 explicitly hypothesized in its own commit message:

> The conv-26→conv-30 deadlock root cause may therefore lie inside
> the persistent-loop surface itself (e.g. per-call
> httpx.AsyncClient context-manager teardown accumulation) rather
> than in a sibling asyncio.run.

This chip confirms that hypothesis and ships the fix.

## What this chip changes

1. **`chimera/providers/openrouter.py`** — `OpenRouterProvider` now
   holds a lazy `httpx.AsyncClient` instance. `_get_client()` creates
   it on the loop that first calls it; subsequent calls reuse the
   same client. If a future caller submits from a different loop
   (the production path always uses the persistent loop, but tests
   can construct ad-hoc loops), the cached client is closed and a
   new one is bound to the current loop. `complete_with_tools` and
   `stream` both consume the shared client. `aclose()` lets tests
   tear down explicitly.

2. **`chimera/cli.py`** — `_build_openrouter_answer_fn` wraps each
   `complete_with_tools` call in `asyncio.wait_for(...,
   timeout=CHIMERA_ANSWER_TIMEOUT_S)` (default 240 s, env-overridable).
   This is a belt-and-suspenders safety net: httpx already enforces
   its own 60 s connect/read timeout × 3 retries, but if anything
   wedges the coroutine outside httpx (e.g. an executor that never
   schedules), `wait_for` cancels and the sweep continues with a
   per-item error rather than a multi-hour hang.

3. **`chimera/evals/locomo.py`** — `run_batch` gains a
   `CHIMERA_LOCOMO_TRACE=1` env-gated stderr trace that emits one
   line per phase per item (conv start / ingest done / answer done,
   each with elapsed seconds). The prior `logger.info(...)` from PR
   #94 was silently dropped because the CLI does not configure the
   root logger, so the per-conversation marker the operator needed
   never appeared in sweep logs. stderr writes regardless of logger
   config.

4. **`tests/test_providers.py`** — two new offline tests:
   `test_openrouter_provider_reuses_single_asyncclient` pins the
   contract that two calls to `_get_client()` return the same
   object; `test_openrouter_provider_rebinds_client_on_loop_change`
   covers the loop-rebinding branch.

## Relation to PRs #93 / #94 / #95 / #96

* **PR #93** routed the OpenRouter answer_fn through the persistent
  loop. Closed the per-call `asyncio.run` shutdown wedge. **Stays.**
* **PR #94** extended the persistent-loop pattern to the other
  `asyncio.run` sites in the CLI/loop path. **Stays.**
* **PR #95** closed the iterdir-vs-unlink race in the LoCoMo adapter
  cleanup. **Stays.**
* **PR #96** bounded the synchronous Ollama embedder timeout +
  retry. Closed the embedder-side hang on the hybrid-retrieval path.
  **Stays.**
* **This chip** is the focused follow-up after the broader audit:
  the last cumulative-state wedge that survived all four predecessor
  fixes. None of the prior ADRs (0142 / 0143 / 0144 / 0145) and F1
  / F3 numbers are touched.

## Acceptance

* Offline unit tests (1,551 passing + 2 new) — pass.
* `CHIMERA_LOCOMO_TRACE=1` 10-conversation sweep with
  `--hybrid-retrieval --retrieval-top-k 8` passes the conv-26 →
  conv-30 boundary that previously deadlocked. Full 1,986-item
  sweep is the operator-side acceptance run (3–5 h wall on
  gpt-4o-mini answerer); this chip is gated on that run, not by
  this PR.
* F1 (no `--hybrid-retrieval`) untouched — adapter and provider
  changes are inert when the flag is off, save the shared
  AsyncClient (which still benefits F1 if anyone runs it with
  `--answer`).
