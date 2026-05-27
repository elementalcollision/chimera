# F2 blocked — N-dependent hybrid-retrieval deadlock on LoCoMo

**Date**: 2026-05-27
**Status**: BLOCKED — F2 paused, bug chip required before resumption
**Author**: Chimera-Agent (F2 chip operator)
**Charter**: Root-cause and fix the N-dependent hybrid-retrieval LoCoMo deadlock; once green, F2 resumes.

## Symptom

`chimera evals locomo --hybrid-retrieval --retrieval-top-k 8` deterministically hangs at startup when the slice of `data/locomo10.json` includes a specific conversation in the iteration order — specifically `conv-42`. The hang reproduces across multiple invocations, is N-dependent (small slices succeed, slices that reach conv-42 hang), and is not transient (not a rate-limit, not a network blip).

When hung:
- Process is at 0% CPU.
- No open network sockets (`lsof -i` returns empty).
- Main thread parked in `kqueue/kevent` (asyncio event loop idle).
- Worker thread parked on `SimpleQueue.get` (asyncio's default executor's idle queue).
- Output JSONL never created; stdout buffer empty under `PYTHONUNBUFFERED=1`.

The F1 baseline (no `--hybrid-retrieval`, full 1986-item corpus) shipped cleanly on the same codebase. The smoke variant (2 QAs from conv-26 only, with `--hybrid-retrieval`) also completes in seconds. The hang is specific to the hybrid-retrieval codepath crossed with content from a specific conversation.

## Bisection table

Slice files: `/tmp/chimera-f2-locomo/slice-{1,2,3,4,5,10}conv.json`. Each slice trims QAs to 2 per conversation so the runtime is dominated by setup + first-question retrieval, not bulk API calls. CLI invocation per slice (only `--items`, `--out`, `--mind-dir` vary):

```
chimera evals locomo \
  --items /tmp/chimera-f2-locomo/slice-Nconv.json \
  --answer --answer-model openai/gpt-4o-mini \
  --answer-temperature 0 --answer-max-tokens 2048 \
  --hybrid-retrieval --retrieval-top-k 8 \
  --out /tmp/chimera-f2-locomo/slice-Nconv.jsonl \
  --mind-dir /tmp/chimera-f2-locomo/slice-Nconv-mind
```

With `PYTHONUNBUFFERED=1` and a foreground hard timeout.

| Slice | Conversations | Outcome | Wall | Items |
|---|---|---|---:|---:|
| 1conv | conv-26 | COMPLETED | 36s | 2 |
| 2conv | conv-26, conv-30 | COMPLETED | 55s | 4 |
| 3conv | conv-26, conv-30, conv-41 | COMPLETED | 85s | 6 |
| **4conv** | conv-26, conv-30, conv-41, **conv-42** | **HUNG** | 180s+ kill | 0 written |
| 5conv | conv-26..43 (includes conv-42) | HUNG | 240s+ kill | 0 written |
| 10conv | all 10 (includes conv-42) | HUNG | 240s+ kill | 0 written |

**Threshold: conv-42** — the bisection isolates the trigger to the iteration crossing into the first QA of conv-42.

### Diagnostic confirmation: partial mind dir

After the 4conv hang was killed, `/tmp/chimera-f2-locomo/slice-4conv-mind/` contains:

```
peers/self.md                          (25.3K — written by conv-41's last ingest_history)
wiki/locomo/conv-41-s000.md … conv-41-s015.md  (conv-41 sessions)
```

No `conv-42-*.md` files. No JSONL output (`run_batch` never returned, so `write_results` never ran; the 6 completed in-memory results for conv-26/30/41 were lost on kill). This places the hang **inside the first iteration of conv-42**, before `ingest_history` writes any scratch files for it.

The first thing `ingest_history` does on a new sample_id is `_select_session_indexes(item)`, which (since conv-42 has 29 sessions > top_k=8) invokes `select_top_k_sessions(...)` with the question text and 29 session texts. This calls `embed_fn([question] + 29 session_texts)` — a synchronous HTTP POST to `ollama.deploy.orb.local/api/embed`.

## Stack evidence

From operator's `sample 6748 1` taken while hung (relaunched sweep PID; first sweep PID 5859 had identical stack):

- **Main thread**: parked in `kqueue/kevent` — Python's `selectors.KqueueSelector.select()` called by `asyncio.base_events.BaseEventLoop._run_once`. The event loop is alive but has nothing to wait on.
- **Worker thread**: parked on `_queue.SimpleQueue.get` — the default `ThreadPoolExecutor`'s idle worker waiting for work submission.
- **No httpx active sockets** — neither Ollama (`api/embed`) nor OpenRouter (`chat/completions`) has an in-flight connection.

Cross-referenced against:
- `chimera/evals/locomo.py:439` — `_select_session_indexes` synchronously calls `select_top_k_sessions(..., embed_fn=self._embed_fn)`.
- `chimera/evals/hybrid_retrieval.py:232` — `vecs = embed_fn(to_embed)` synchronous call (no asyncio).
- `chimera/evals/hybrid_retrieval.py:389` — `OllamaEmbedder.__call__` uses synchronous `httpx.Client(timeout=300.0)`.
- `chimera/cli.py:1241–1254` — `answer_fn` wraps `asyncio.run(provider.complete_with_tools(...))` per call. This is the only asyncio.run surface in this codepath.

The "asyncio idle, no sockets" stack is **inconsistent with a stuck `httpx.Client.post`** — that would show an active socket on the embed endpoint. It is consistent with **an asyncio.run that completed setup but its inner coroutine is awaiting something that will never resolve** — e.g. a future never set, or a producer never started. But `answer_fn` only runs after `ingest_history` returns. So either (a) `ingest_history` is hanging silently in a non-network way, or (b) the embed call returned, ingest_history wrote files, and then `answer_fn` deadlocked — but the missing `conv-42-*.md` files contradict (b).

**Most plausible**: a state transition or import that happens lazily on the first `answer_fn` invocation following the conv-26/30/41 cycle of `ingest_history` calls AND embed calls. Conv-42's specifically larger or specifically shaped session text may push the Ollama embedder into a regime where the HTTP response arrives but the parsed payload is malformed, with the worker hanging on a partial read. But that would still show a socket. Confused state.

A weaker possibility: the `OllamaEmbedder` is making the POST synchronously, blocking the main thread; the asyncio event loop visible in `sample` is from a previous `asyncio.run` whose cleanup is racing. That would explain "main parked in kevent" being a stale snapshot of the prior answer_fn's loop teardown.

## Reproducer

Smallest hanging slice: `/tmp/chimera-f2-locomo/slice-4conv.json` (conv-26 + conv-30 + conv-41 + conv-42, 2 QAs each). Hangs deterministically at startup of conv-42's first QA. 4-minute timeout reliably reproduces.

Smallest single-conversation hanging hypothesis: **conv-42 alone**, not yet tested. Worth running as the first step of the bug-chip — if `slice-conv-42-only.json` hangs immediately, the problem is conv-42-content-intrinsic. If it works alone but hangs in the 4conv slice, the problem is **stateful** (something accumulated across conv-26/30/41 that interacts with conv-42's content).

## Hypothesis list

Ranked by plausibility given the evidence.

1. **Ollama embedder per-process degradation with cumulative session text load.** After embedding 19+19+32 = 70 distinct session texts (conv-26/30/41), the local Ollama instance hits an internal limit (KV cache exhaustion, RAM pressure, model reload). Conv-42's 29-session embed batch fails to respond. `httpx.Client(timeout=300.0)` should eventually surface this — but the stack says no socket open, contradicting a stuck POST. Subhypothesis: the embedder connection actually returned (200 OK but malformed/empty payload), the code at `hybrid_retrieval.py:233` then raises `RuntimeError("returned N vectors for M inputs")` which is caught at a higher level and treated as falling back — but the resulting state then deadlocks the next operation.
2. **OpenRouter provider client connection-pool exhaustion or warm-cache key collision.** `OpenRouterProvider()` is instantiated once per `_build_openrouter_answer_fn` call (CLI line 1239), THEN `asyncio.run` is called per question (line 1254). If httpx's async client is created in `provider.__init__` and bound to the FIRST loop, then subsequent `asyncio.run` calls create new loops but reuse the client → deadlock on connection-pool wait. This is a well-known asyncio anti-pattern. Why N-dependent: keep-alive sockets accumulate; one of the conv-41-answering connections may not close cleanly before conv-42's first answer attempts to acquire a new connection from a stale pool. Investigation entry point: `chimera/providers.py` — does `OpenRouterProvider.__init__` create an `httpx.AsyncClient`? If yes, this is almost certainly the bug.
3. **`gather_dialectic_context` or `build_dialectic_prompt` doing async work that races across `asyncio.run` calls.** Same per-question `asyncio.run` pattern. If `gather_dialectic_context` (called inside `LoCoMoAdapter.answer` at locomo.py:465) does ANY async work via a module-level client, the same multi-loop-one-client trap applies.
4. **BM25 SQLite FTS5 in-memory index corruption on a specific conv-42 session text.** `hybrid_retrieval.py:117` opens `sqlite3.connect(":memory:")` per call. A specific token in conv-42's session text could trip FTS5 query parsing (especially around special chars `*`, `"`, `:`). Why hang vs raise: `bm25_rank` catches OperationalError and returns empty BM25 ranks, then the code at `select_top_k_sessions:251` returns early with `selected=list(range(top_k))` — no hang path. Therefore this is **unlikely** unless the exception handling has a bug.
5. **Conv-42 content triggers a regex / tokenizer infinite loop in `_session_to_text` or `bm25_tokenize`.** Pure-Python regex backtracking on adversarial input. Would show CPU≠0% though — the stack says 0% CPU, ruling this out.
6. **An asyncio.gather-style fan-out we haven't located.** `grep` of `chimera/evals/hybrid_retrieval.py` showed zero `asyncio|gather|Queue|Semaphore|to_thread` matches. `chimera/evals/locomo.py:559` is a plain synchronous `for item in items` loop. So this hypothesis is weaker than (1)–(3) but should be ruled out by `grep -r "gather\|asyncio.run\|to_thread" chimera/` and reviewing each surface.

## Investigation starting points

1. **`chimera/providers.py` — `OpenRouterProvider` async client lifecycle.** If `__init__` creates an `httpx.AsyncClient` and `complete_with_tools` uses it, the multi-`asyncio.run`-one-client pattern (hypothesis 2) is confirmed. Fix: instantiate the async client inside the coroutine, or use `asyncio.run` once for the whole sweep instead of per-question.
2. **Add per-iteration trace logging in `chimera/evals/locomo.py:run_batch`.** A single `logger.info(f"item {n}: {item.sample_id}::{item.item_id}")` line before `adapter.ingest_history(item)` would pinpoint the exact item where the hang occurs and convert this from a guess-and-check to a one-shot diagnosis. Land this even before attempting a fix.
3. **Standalone reproducer harness for the Ollama embedder under cumulative load.** Construct a script that embeds conv-26/30/41/42 session texts back-to-back (no chimera). If the standalone reproducer hangs at conv-42, hypothesis 1 is confirmed. If it doesn't, the bug is chimera-side (hypothesis 2/3).
4. **Re-run with `OLLAMA_URL=invalid` to force BM25-only.** If the same 4conv slice completes under BM25-only, the embedder is the culprit (hypotheses 1 / 4 / 5). If it still hangs, the bug is in the chimera answer path (hypotheses 2 / 3).

## Charter for the new chip

> **Root-cause and fix the N-dependent hybrid-retrieval LoCoMo deadlock; once green, F2 resumes.**
>
> - Land per-iteration logging in `run_batch` (low-risk, high-diagnostic-value) as step 1.
> - Triage hypotheses 1, 2, 3 with the standalone harness + BM25-only fallback experiment.
> - Fix the identified root cause without expanding scope (no perf work, no refactor).
> - Re-run the 4conv slice as the green gate; then the full 1986-item sweep as the F2 prerequisite.
> - Budget: ~$2 in API + 2-4hr engineering.
>
> F2 charter (this chip) remains valid and unchanged after the fix lands. ADR 0142 amendment, ADR 0145 gate clearance, and PR title remain pre-registered against the F1 49.35% / F3 σ=0.46pp baseline.

## Hard constraints honored (this chip's deliverable)

- Did NOT modify `chimera/evals/locomo.py`, `chimera/evals/hybrid_retrieval.py`, `chimera/cli.py`.
- Did NOT modify any ADR.
- Did NOT open a PR for F2.
- No code change beyond test fixture JSON files in `/tmp/`.

## Artifacts

- Bisection slices: `/tmp/chimera-f2-locomo/slice-{1,2,3,4,5,10}conv.json`
- Per-slice run script: `/tmp/chimera-f2-locomo/run_slice.sh`
- Slice logs: `/tmp/chimera-f2-locomo/slice-{1,2,3}conv.log` (completed; show end-of-run summary lines)
- Hung-slice partial mind dirs: `/tmp/chimera-f2-locomo/slice-{4,5,10}conv-mind/wiki/locomo/` (containing last successful conversation's session files)
- F1 baseline (for F2 comparison once unblocked): `/tmp/locomo-f1/hypotheses.graded.jsonl`
- F2 charter doc (skeleton already drafted): `mind/research/locomo-f2-retrieval-ablation-2026-05-27.md` (verdict section blank)

## Operational metrics

- Wall time spent on F2 chip before block: ~75 min (including failed launches).
- API spend: ~6 items × ~10K tokens × gpt-4o-mini ≈ $0.05. Well under the $9 cap.
- Bug-chip block discovered via two-launch-then-bisect protocol; future LoCoMo chips with new flags should run a 4-conv smoke as a prerequisite before launching the full corpus, since the smoke (1 conv) is insufficient to surface this class of bug.

## Linked decisions

- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — hybrid-retrieval decision; this chip's bug lives in its LoCoMo-adapter integration. ADR substantive content not modified.
- [ADR 0144](../../docs/adr/0144-locomo-benchmark-integration.md) — LoCoMo adapter that owns the hung codepath.
- [ADR 0145](../../docs/adr/0145-locomo-noise-envelope.md) — F2/F4 read-out gates, pre-registered and unaffected by this delay.
- [F1 baseline](./locomo-baseline-full-2026-05-26.md) — comparator once F2 unblocks.
- [F3 envelope](./locomo-noise-envelope-2026-05-27.md) — σ bound once F2 unblocks.
- [F2 charter draft](./locomo-f2-retrieval-ablation-2026-05-27.md) — verdict section blank until F2 resumes.
