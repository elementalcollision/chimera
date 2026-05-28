# v35 SQLite thread-affinity fix — design note

**Date:** 2026-05-27
**Chip:** 1 of the v35 postmortem ladder (`fix/sqlite-thread-affinity`)
**Diagnosis source:** PR #104 (merged at `0a0f598`)
**Status:** fix landed in a worktree; PR open against `main`; awaiting operator merge.

---

## The defect

`chimera/_async_loop.py:49` spawns a daemon thread (`chimera-async-loop`)
and routes every `run_on_persistent_loop(coro)` call through
`asyncio.run_coroutine_threadsafe` onto that single background loop.
`chimera/core/loop.py:150` opens `self._db = open_and_init(self._db_path)`
in `Loop.__init__`, which runs on the *calling* thread — the main
thread under `chimera run`. The connection was created by
`chimera/memory/store.py:201` via `sqlite3.connect(...)` *without*
`check_same_thread=False`, so Python's default `True` makes every
subsequent `self._db.execute(...)` from the loop-thread raise:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only
be used in that same thread.
```

Empirically reproduced inside this chip:
`tests/test_chimera_run_e2e.py` failed on `main` with the exact error
at `chimera/memory/entities.py:147` during `_phase_wake`. The new test
now passes after the fix.

## Option A vs Option B — what I picked and why

**Picked: Option B** (`check_same_thread=False`).

The choice was straightforward once I counted call sites. The `Loop`
object passes `self._db` to *seven* sub-objects in `__init__` —
`ActExecutor`, `SubAgentRunner`, `Planner`, plus four more downstream
constructors (loop.py:169, 175, 200, 216, 222, 229). Every one of those
holds a long-lived reference and uses it from inside `run_one_cycle`.
Option A's "lazy on loop-thread" rewrite would have to either (a)
reach into all seven constructors and turn each into a lazy proxy, or
(b) defer Loop's own DB open until first access *and* defer each
sub-object's DB usage. Both expand the diff far past the 6-file cap
and introduce a proxy abstraction with no other consumer.

Option B is one line of substantive change — adding
`check_same_thread=False` to the `sqlite3.connect(...)` call inside
`chimera/memory/store.py:connect()`. The architectural invariant that
makes it safe is already in place: the persistent loop serializes
every coroutine onto one background thread, so there is no concurrent
writer. The only main-thread touch after `__init__` is `Loop.close()`,
which runs in the `finally` of `chimera/cli.py:1969` — strictly *after*
`fut.result()` has resolved on the loop thread. No race window.

The lock that the spec offered as "defensive" would not actually
protect against anything: the only realistic race (close vs. query) is
already excluded by the future-resolution ordering. Adding a lock
inside `Loop` also wouldn't cover the seven sub-objects that hold the
same connection. So it would be ornamental code that lies about
guarantees it doesn't provide. I left it out.

If, post-merge, we want a second-level guarantee independent of the
serialization invariant, the cleaner intervention is to enforce that
*all* `Loop` access flows through `run_on_persistent_loop` — not to
sprinkle locks on a connection that already lives in a single-thread
world by construction.

## The systemic-gap test (the load-bearing artifact)

Two consecutive v35-soak postmortems (PR #102 → PR #103 detector fix;
PR #104 → this chip) found cascading infrastructure defects on the
exact same code path: `chimera run` invoked from a non-main branch in
a `git worktree add`-created secondary. Both shipped because no test
ever exercised that path end-to-end.

`tests/test_chimera_run_e2e.py` closes that gap. It does **not** stub
the detector, **not** stub the SQLite layer, and **not** stub the
persistent loop. It builds a real on-disk repo with `git init` + a
commit, `git worktree add`s a secondary on `chip/e2e-test`, `chdir`s
into it, points `CHIMERA_MIND_DIR` / `CHIMERA_STATE_DIR` at tmp paths,
and invokes `chimera.cli.main(["run"])`.

**What this would have caught:**

* **PR #103 (ADR 0141 detector misfire):** the prior detector
  discriminated primary vs. secondary worktrees by `--show-toplevel`,
  which returns the same value in both, so every secondary refused
  with exit 2. This test would have hit `rc == 2`, asserting against
  the documented `rc == 0`, and failed pre-merge.
* **PR #104 (this chip — SQLite thread mismatch):** as the failing
  reproduction above demonstrated, this test fails on current `main`
  with `sqlite3.ProgrammingError` from inside `_phase_wake`.
* **The next cascading defect on this path:** whatever it is, it will
  also fail this test, because the test exercises the real surfaces
  end-to-end. That is the durable value of this artifact, not the
  one-line SQLite fix it currently locks in.

A second, tighter regression test
(`test_persistent_loop_drives_run_one_cycle_against_real_sqlite`)
lives in the same file. It skips the CLI + detector and drives
`run_on_persistent_loop(Loop.run_one_cycle())` directly, which gives
us a sharper error message if a future regression isolates the
thread-affinity bug from the surrounding CLI logic.

## Honest disclosures

* **Two cascading defects in two PRs on the same path** is a process
  signal, not a code signal. The test we added is the
  process-level correction — it makes the next iteration of this
  pattern impossible to ship without surfacing first.
* **I did not amend ADR 0141** in this chip. The detector ADR is
  about chip-branch-jump refusal and is unchanged. Adding an ADR
  cascade-lesson subsection felt like documentation expansion past
  the locked scope; we can do it as a small follow-up if the
  operator wants it called out.
* **I considered a third regression test** that runs `chimera run`
  via `subprocess.run([sys.executable, "-m", "chimera", "run"], …)`
  to exercise the *real* process entry. I left it out: it would
  duplicate coverage with significantly higher wall-clock cost, and
  the in-process `_cli.main(["run"])` path already drives every
  thread-affinity surface that matters. If we later want true
  subprocess isolation, it should be one shared fixture rather than
  per-bug bolt-ons.

## What's next (operator-side)

After this PR lands, **relaunch v35** — this will be the third
attempt. The first attempt died on PR #102's detector bug; the second
on PR #104's SQLite bug; this fix unblocks the path. The relaunch is
explicitly **not part of this chip**.

## Scope tally

* Files touched: 2
  * `chimera/memory/store.py` — added `check_same_thread=False` +
    explanatory comment.
  * `tests/test_chimera_run_e2e.py` — new, 2 tests.
* Test count delta: 1556 → 1558 (+2). Existing 1556 unchanged.
* No new CLI flags, env vars, or ADR amendments.
* No modification to PR #103's detector code.
