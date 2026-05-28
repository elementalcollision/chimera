# v35 soak postmortem (relaunch #2) — persistent asyncio loop crosses SQLite's thread boundary

**Date**: 2026-05-28 (relaunch ≈21:16 local, post-[#103](https://github.com/elementalcollision/chimera/pull/103))
**Soak**: `scripts/long_cycle_soak_v35.sh`, second attempt
**Outcome**: operational FAIL before substantive work began. New, distinct failure mode from attempt #1.
**Headline**: The v4.115.0 persistent asyncio loop ([#93](https://github.com/elementalcollision/chimera/pull/93) / [#94](https://github.com/elementalcollision/chimera/pull/94)) runs each `chimera run` cycle on a daemon background thread, but the `Loop`'s `sqlite3.Connection` is opened on the main thread. SQLite's default `check_same_thread=True` rejects the cross-thread access, so every `chimera run` iteration crashes with `sqlite3.ProgrammingError` before doing any substantive work. ADR 0141 layer-2 detector ([#103](https://github.com/elementalcollision/chimera/pull/103)) now passes correctly — the soak got further than attempt #1 — but stopped immediately at the next defect.

---

## Substantive layer

**No substantive output, again.** Phase 1 ran 3 iterations (~50s) before the supervisor terminated; every iteration exited 1 with a `sqlite3.ProgrammingError` traceback. Phase 2 never started.

- Phase 1 design recommendation: **N/A**
- Hypothesis classification (H1 / H2 / H3): **N/A**
- Phase 2 outcome: **did not run**
- Auto-generated PR: **none opened**
- Soak worktree (preserved for forensics): `/Users/dave/chimera-soak-v35-2026-05-28-0116`, branch `chimera-soak/v35-2026-05-28-0116`

The F2 temporal-reasoning regression diagnosis remains open after two consecutive infrastructure-level soak failures.

---

## Operational layer

### Failure mode

Every `chimera run` iteration exited 1 with a traceback ending in:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
The object was created in thread id <main>, and this is thread id <chimera-async-loop>.
```

The same error fires from at least three call sites in a single iteration:

1. `chimera/core/loop.py:459 _phase_wake → ensure_current_plan → get_entity_by_name → conn.execute(...)`
2. `chimera/core/loop.py:375 _phase_housekeeping → auto_archive_stale_deprecated → conn.execute(...)` (logged as `auto-archive failed; continuing`)
3. `chimera/core/loop.py:408 _phase_housekeeping → update_wiki_index → ensure_wiki_index → conn.execute("CREATE VIRTUAL TABLE ... fts5 ...")` (logged as `auto-wiki-index update failed; continuing`)

All three originate from the same thread mismatch.

### Root cause — Loop / SQLite / persistent-loop interaction

The persistent-loop module ([chimera/_async_loop.py:36-54](chimera/_async_loop.py:36)) spawns a daemon thread named `chimera-async-loop`, sets an event loop on it, and runs every submitted coroutine there via `asyncio.run_coroutine_threadsafe` ([chimera/_async_loop.py:65](chimera/_async_loop.py:65)).

`chimera run` ([chimera/cli.py](chimera/cli.py) around line 1969 in the soak's snapshot, `run_on_persistent_loop(_loop.run_one_cycle())`) constructs the `Loop` object — including `self._db`, a `sqlite3.Connection` — on the **main thread** before submitting the coroutine. When the coroutine runs on the background thread and calls `self._db.execute(...)`, the connection rejects it.

`sqlite3.connect()` defaults to `check_same_thread=True`, which is appropriate for the previous "fresh `asyncio.run()` per cycle, all on main thread" model but incompatible with the new persistent-loop thread layout.

The chip-branch-jump fix ([#103](https://github.com/elementalcollision/chimera/pull/103)) is doing its job — the soak's worktree is no longer misidentified as the primary, so `chimera run` actually starts. It then crashes on the next gate.

### Why didn't this surface in the F2 chip that introduced the persistent loop?

The F2 hybrid-retrieval chip ([PR #98](https://github.com/elementalcollision/chimera/pull/98)) used `chimera evals locomo`, which runs the eval driver directly — not `chimera run`. The eval driver's database access path is different (or absent at the relevant points). `chimera run` is the agent-loop entry point used by soaks, and the v35 soak is the first post-#94 invocation of it under realistic conditions. The unit tests for `_async_loop.py` ([`tests/test_async_loop_persistence.py`](tests/test_async_loop_persistence.py) if present) exercise the loop with coroutines that don't touch the agent SQLite store from the background thread, so the mismatch is invisible to them.

### Wall-clock & spend

| Metric | Value |
|---|---|
| Total wall | ~50s |
| Iterations completed | 3 (all crashed with the same traceback) |
| Total spend | $0.00 |
| Final cycle count | 0 |
| API calls | 0 |

### Infrastructure shakeout — what we learned anyway

| Mechanism | Source | Exercised? | Result |
|---|---|---|---|
| Chip-branch-jump prevention (Layer 2) | [ADR 0141](docs/adr/0141-chip-branch-jump-layers-2-3.md), fixed in [#103](https://github.com/elementalcollision/chimera/pull/103) | Yes | **PASS** — soak's worktree correctly identified as secondary, `chimera run` started. |
| Persistent asyncio loop | [#93](https://github.com/elementalcollision/chimera/pull/93) / [#94](https://github.com/elementalcollision/chimera/pull/94) | Yes (negatively) | **FAIL** — runs coroutines on a non-main thread without coordinating with the SQLite connection's thread affinity. |
| Shared `httpx.AsyncClient` | [#97](https://github.com/elementalcollision/chimera/pull/97) | No | not reached — SQLite crash precedes provider call. |
| Ollama timeout/retry + BM25 fallback | [#96](https://github.com/elementalcollision/chimera/pull/96) | No | not reached. |
| Witness panel verdicts | — | No | no panel runs. |
| Soft-sentinel / wiring_coordinator | `_soak_common.sh` | No | phase 1 never produced the sentinel target. |

### Honest disclosures

- The soak loop still has no forward-progress check. It dutifully ran 3 iterations at `cycle=0 spend=$0`, classified the failure as "engine skips and gate denials are normal", and would have continued for ~67 more minutes. The recommendation from postmortem #1 to add a "no forward progress" watchdog remains live and would have caught this in seconds.
- The soak preflight recommendation from postmortem #1 (run `chimera doctor` from the new worktree before launching the loop) would *not* have caught this defect, because the SQLite thread mismatch only fires when `chimera run` is invoked, not from `chimera doctor`. A stronger preflight — actually exercising `chimera run` for one cycle with a tiny no-op INBOX — would catch it. Recommend upgrading the preflight check to "one canary `chimera run` from inside the new worktree."
- Two consecutive inaugural-soak failures at distinct infrastructure gates indicates the post-v4.115.0 stack was integration-tested in pieces, never end-to-end against `chimera run` from a secondary worktree. A standalone integration test that drives `chimera run` for one cycle from a fresh `git worktree add`-created branch would close both gaps.

---

## Recommended next chips

1. **Fix the SQLite/persistent-loop interaction** (highest priority — still blocking every soak).
   Two viable approaches:
   - **Open the SQLite connection on the loop thread.** Defer `Loop.__init__`'s `sqlite3.connect(...)` until the first call dispatched on the background thread. Cleanest; requires moving the connection-creation site.
   - **Open the connection with `check_same_thread=False`** and add an explicit `threading.Lock` around all SQLite access. Smaller diff but introduces a global lock; acceptable since the persistent loop already serializes work.
   Add a regression test that constructs a `Loop`, submits `run_one_cycle()` via `run_on_persistent_loop`, and asserts no `ProgrammingError`.

2. **Add the canary-`chimera run` preflight** to `_soak_common.sh`. After `git worktree add`, run one tiny `chimera run` cycle with a no-op INBOX inside the new worktree; abort the soak if it exits non-zero. Cost: a few seconds. Benefit: catches every "soak can't start" defect at the door.

3. **Add a forward-progress watchdog** to the soak loop (carried over from postmortem #1, still warranted). Abort with `FATAL: no forward progress` if N consecutive iterations report `cycle=0 spend=$0`.

4. **Re-charter v35** after chips 1-3 land. F2 temporal-regression investigation remains open.

---

## Substantive verdict

**FAIL** — no diagnosis produced. F2 temporal-regression investigation remains open after two failed soak attempts.

## Operational verdict

**FAIL** — different gate than attempt #1. Attempt #1 was blocked by the ADR 0141 detector (fixed by [#103](https://github.com/elementalcollision/chimera/pull/103)); attempt #2 is blocked by SQLite/persistent-loop thread mismatch. The post-v4.115.0 stack has two distinct integration defects on the path to executing one productive `chimera run` cycle from a secondary worktree.

## Forensic artifacts (preserved)

- Soak log (attempt #2): `state/long_cycle_v35_2026-05-28-0116.log`
- Soak worktree (attempt #2): `/Users/dave/chimera-soak-v35-2026-05-28-0116` (intact, branch `chimera-soak/v35-2026-05-28-0116`)
- Launch wrapper log: `/tmp/v35-soak-launch-2.log`
- Attempt #1 artifacts (preserved per [PR #102](https://github.com/elementalcollision/chimera/pull/102)): `state/long_cycle_v35_2026-05-28-0054.log` and worktree `/Users/dave/chimera-soak-v35-2026-05-28-0054`.
