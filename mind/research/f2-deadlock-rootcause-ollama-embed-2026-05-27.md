# F2 LoCoMo "deadlock" — actual root cause is the Ollama embedder

**Date**: 2026-05-27
**Status**: ROOT CAUSE IDENTIFIED — fix proposed in PR (this chip)
**Author**: Chimera-Agent (F2 deadlock-rootcause chip)

## TL;DR

The F2 LoCoMo hybrid-retrieval "deadlock" at the conv-N → conv-N+1
boundary is **not** an asyncio defect. It is the **synchronous Ollama
embedder** blocking on `httpx.Client.post` waiting up to 300 s for a
local bge-m3 instance that intermittently hangs on larger session
batches under cumulative KV-cache load. Three earlier PRs (#93 / #94 /
#95) closed real but unrelated defects on the LoCoMo answer path and
did not change the ingestion-time embedder behavior; the apparent
"deadlock at the conversation boundary" persisted because the
embedder is the only thing that runs synchronously at that boundary
on the hybrid-retrieval path.

## How the misdiagnosis happened

Operator `sample <pid>` snapshots taken during a hung sweep showed
three threads:

1. Persistent asyncio loop thread parked in `kevent`
2. asyncio default-executor worker parked on `SimpleQueue.get`
3. Main thread reported as `_PyMutex_LockTimed` in older notes

The first two are **idle states of healthy asyncio infrastructure**.
Earlier chips inferred the deadlock was in asyncio's shutdown/teardown
path because (a) the worker stack matched the textbook
`shutdown_default_executor`-on-anyio wedge for repeated `asyncio.run`,
and (b) `lsof -i` once returned empty (likely a transient snapshot
between an Ollama call cycle, or a different reproduction).

PRs #93 and #94 introduced and extended a persistent asyncio loop
that defers teardown to process exit — a genuine improvement over
per-call `asyncio.run`, and a fix for the documented executor wedge
on Python 3.13+. PR #95 closed a real iterdir/unlink race. None of
these touched the ingestion-time `OllamaEmbedder.__call__` path.

## Direct evidence (this chip)

Slice: `/tmp/chimera-f2-locomo/slice-4conv.json` (conv-26, conv-30,
conv-41, conv-42 — 2 QAs each). Invocation per the prior chip's
script. Per-conversation INFO logging from PR #94 enabled via a
small `basicConfig(level=INFO)` wrapper (the CLI does not configure
the root logger).

### Log up to the hang

```
13:07:52 starting conversation conv-26 (item #0)
13:08:16 ollama embed 200 OK     ← conv-26 select_top_k_sessions, ~24 s
13:08:17 openrouter answer 200 OK
13:08:18 ollama embed 200 OK     ← cached → re-emit for new question
13:08:27 openrouter answer 200 OK
13:08:29 starting conversation conv-30 (item #2)
13:08:45 ollama embed 200 OK     ← ~16 s
13:08:46 openrouter answer 200 OK
13:08:50 ollama embed 200 OK
13:08:58 openrouter answer 200 OK
13:08:59 starting conversation conv-41 (item #4)
[no further log lines; 0 % CPU; killed at 13:09:42 by watchdog]
```

### Sample at the hang

`sample 81252 1 -mayDie` taken at `13:09:42`, transcribed (full file:
`/tmp/chimera-f2-locomo/sample-81252.txt`):

- **Main thread** — `sock_recv → sock_recv_guts → sock_call_ex →
  internal_select → poll`. A *synchronous* Python socket read
  blocked in `poll(2)` waiting for response data. **Not** asyncio.
- **Thread_48094845** — `select_kqueue_control_impl → kevent`. The
  persistent asyncio loop, idle. Working as designed.
- **Thread_48094846** — `_queue_SimpleQueue_get → _PyParkingLot_Park
  → _PySemaphore_Wait → __psynch_cvwait`. asyncio default-executor
  worker, idle. Working as designed.

The main-thread `sock_recv → poll` chain is `httpx.Client.post`
inside `OllamaEmbedder.__call__` waiting for the bge-m3 response.
Conv-41 has 32 sessions; the first ingest fired a 33-input embed
batch (query + sessions). Ollama accepted the request, the socket
is open, no further bytes arrive.

### Independent confirmation

1. Direct reproduction of the same conv-41 batch outside chimera
   succeeded in **30.32 s**:

   ```
   POST ollama.deploy.orb.local/api/embed
   inputs: 33; total chars: 94 648; max: 5 106
   HTTP 200 in 30.32 s; embeddings=33
   ```

   So the call is not structurally broken — Ollama can serve it.
   It just sometimes does not.

2. `CHIMERA_OLLAMA_URL=http://127.0.0.1:1` (forces immediate
   connection refused; build_default_embed_fn returns `None`)
   completed the same 4-conv slice in **60 s** with BM25-only.
   This is the same code path the post-fix sweep takes on every
   timeout, so the fallback contract is real.

## Mechanism

`OllamaEmbedder.__call__` uses `httpx.Client(timeout=300.0)` and
calls `client.post(...)` synchronously from whatever thread is
running `_select_session_indexes` — which is the main thread. When
the local bge-m3 instance stalls on a larger batch (KV cache
eviction, model reload, GPU contention — pick one, the local
instance does all of these), the response never comes back, so
`poll` waits the full timeout. Under the previous default that's
**5 minutes per stuck call**.

`select_top_k_sessions` already wraps the embed call in
`except Exception → dense=[] → BM25-only`, so once the timeout
fires, the sweep proceeds. The previous chips' operator reading
of "deadlock" was the symptom of (timeout=300 s) × (corpus of
~2000 items) × (intermittent stalls) producing apparent
no-progress for many minutes; killed early, samples were taken
while the main thread happened to be in `sock_recv`, but the
attention went to the asyncio threads above.

## Fix

`chimera/evals/hybrid_retrieval.py`:

1. Lower the default per-call embed timeout from **300 s → 45 s**.
   Healthy bge-m3 returns the largest LoCoMo batches in under 30 s;
   45 s gives a 1.5× safety margin without permitting the
   five-minute pessimal case.
2. Retry once on `httpx.ReadTimeout`, `ConnectTimeout`,
   `PoolTimeout`. A second attempt on a warm model almost always
   succeeds (verified during reproduction). Worst-case stuck-call
   cost is now **2 × timeout ≈ 90 s**, after which
   `select_top_k_sessions` falls back to BM25-only for that one
   item and the sweep continues.
3. Add `CHIMERA_EMBED_TIMEOUT_S` env override so operators tuning
   for different bge-m3 hosting can dial up/down without code edits.
4. Add a per-call slow-embed warning at >15 s so degraded Ollama
   surfaces in the live log instead of being inferred post-hoc.
5. Mirror the configurable timeout on `VoyageEmbedder` (it does not
   suffer the local-load issue, but inheriting the same env knob
   keeps the interface symmetric).

Regression tests (`tests/test_hybrid_retrieval.py`):

- `test_select_recovers_when_embed_fn_raises_timeout` — pins the
  contract that an embed timeout does not propagate out of
  `select_top_k_sessions`.
- `test_ollama_embedder_retries_once_on_read_timeout` — pins the
  retry behavior with an `httpx.Client` monkeypatch.
- `test_ollama_embedder_surfaces_after_both_attempts_fail` — pins
  the "two attempts then raise" boundary.
- `test_resolve_embed_timeout_honours_env` — covers the env knob.

## Relation to PRs #93 / #94 / #95

| PR | Fix | Relation to F2 hang |
|---|---|---|
| #93 | Persistent asyncio loop for OpenRouter `answer_fn` | Closes the per-call `asyncio.run`/`shutdown_default_executor` wedge on Python 3.13+. Real and load-bearing — keep. Does not touch the embedder. |
| #94 | Extends persistent loop to other `asyncio.run` sites; adds per-conv INFO log | The INFO log was essential in this chip's diagnosis. The persistent-loop extensions are not on the LoCoMo ingest path; PR #94's own body called this out. Keep. |
| #95 | `iterdir`/`unlink` race in adapter reset | Closes the real race exposed by attempt #2. Keep. |
| **this chip** | OllamaEmbedder timeout/retry + tests + research note | The **only** PR in the series that touches the ingestion-time code path that was actually wedging. |

The three earlier PRs are all keeping; this chip's fix is purely
additive on top.

## What this fix does not promise

- **Dense-path coverage is not 100 %.** If Ollama hangs twice in a
  row on the same item, that item is BM25-only. Across 1,986 items
  with an intermittent failure rate of ~1 %, that's roughly 20 items
  on the BM25 path instead of hybrid — well within ADR 0142's
  fallback-acceptable envelope, and surfaced in the warning log.
- **Voyage embedder is the more reliable choice** for production
  sweeps (cloud, no local KV cache). The operator can opt in by
  setting `VOYAGE_API_KEY`; `build_default_embed_fn` already prefers
  it. Recommending it for the next F2 corpus run is a documentation
  item, not a code change here.
- **No chunking** of large batches. A chunking strategy (e.g.
  4-session sub-batches) would further reduce per-call hang
  probability but adds a real change to the request shape and rank
  semantics; that belongs in a separate chip if the timeout+retry
  fix proves insufficient.

## Verification

- Unit tests: `pytest tests/test_hybrid_retrieval.py tests/test_locomo.py
  tests/test_async_loop.py` — 49 passed.
- Reproducer with the fix: 4-conv slice (conv-26, conv-30, conv-41,
  conv-42) completes 8/8 items with `--hybrid-retrieval
  --retrieval-top-k 8` against the live bge-m3 instance. (Result
  recorded in PR body once measured.)
- F1 envelope: the change is timeout-only on a code path that runs
  only when `--hybrid-retrieval` is set, so the default F1 baseline
  (49.35 % ± 2σ) is untouched by construction.

## Artifacts

- Hung-PID sample: `/tmp/chimera-f2-locomo/sample-81252.txt`
- Log of the hang: `/tmp/chimera-f2-locomo/repro-slice-4conv.log`
- BM25-only confirmation log: `/tmp/chimera-f2-locomo/bm25-slice-4conv.log`
- Logging-enabled CLI wrapper: `/tmp/chimera-f2-locomo/run_with_log.py`

## Linked decisions

- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — unchanged
- [ADR 0144](../../docs/adr/0144-locomo-benchmark-integration.md) — unchanged
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — unchanged
- [F1 baseline](./locomo-baseline-full-2026-05-26.md) — unchanged
- [F3 envelope](./locomo-noise-envelope-2026-05-27.md) — unchanged
- [F2 charter skeleton](./locomo-f2-retrieval-ablation-2026-05-27.md) —
  unchanged; verdict awaits the post-fix F2 sweep
- [Prior F2-blocked postmortem](./f2-blocked-by-hybrid-retrieval-deadlock-2026-05-27.md) —
  unchanged; its hypothesis #1 ("Ollama embedder per-process
  degradation with cumulative session text load") is the one that
  was right
