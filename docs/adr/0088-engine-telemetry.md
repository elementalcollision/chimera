# ADR 0088 — Engine telemetry: `engine_runs` table + `caller` column (v4.69)

**Status:** Accepted (2026-05-20)

## Context

`mind/postmortems/engine-telemetry-2026-05-20.md` (Chimera's self-
critical post-mortem of the v1.1 engine architecture, anchored in
live DB data) named five improvements ranked by leverage. This
ADR ships **P1** (unified engine_runs table) and **P4** (caller
column on api_calls) — the pure-plumbing items that have no
policy questions and that every subsequent proposal (P2, P3, P5)
depends on.

The post-mortem's headline finding:

> Across 38 cycles I have exactly ONE ledger-recorded engine
> firing (reflection at cycle 13). `last_runs.json` shows two days
> of activity. `mind/CHRONICLE.md` shows six entries. That's
> three sources of truth disagreeing about how many times the
> engines ran.

Three independent stores meant any honest answer to "did the
engines run today, and how useful were they?" required reconciling
three formats by hand. The dashboard's engine-telemetry widget
(v4.51) counted api_calls per model — which conflated engines
with ACT calls on the same model.

## Decision

### 1. New `engine_runs` table (P1)

`chimera/memory/store.py` — single source of truth, one row per
engine firing:

```sql
CREATE TABLE IF NOT EXISTS engine_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    engine              TEXT NOT NULL,        -- discovery|curiosity|reflection
    cycle               INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,        -- success|skipped|failed|running
    skip_reason         TEXT,
    api_calls           INTEGER NOT NULL DEFAULT 0,
    tokens_in           INTEGER NOT NULL DEFAULT 0,
    tokens_out          INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL,
    chronicle_added     INTEGER NOT NULL DEFAULT 0,
    mutations_proposed  INTEGER NOT NULL DEFAULT 0,
    summary             TEXT                  -- 200-char excerpt
);
CREATE INDEX idx_engine_runs_engine ON engine_runs(engine);
CREATE INDEX idx_engine_runs_cycle ON engine_runs(cycle);
```

New module `chimera/memory/engine_runs.py`:

- `start_engine_run(conn, *, engine, cycle) -> int` — opens a
  `status="running"` row, returns the row id. A crash leaves a
  visible orphan row (operator spot-check signal).
- `finish_engine_run(conn, run_id, *, status, ...)` — closes with
  status + counters + summary. Idempotent.
- `list_engine_runs(conn, *, engine=None, limit=50)` — newest-first.
- `engine_runs_summary(conn)` — `{engine: {status: count}}` for
  doctor / dashboard.

Each engine (`chimera/engines/discovery.py`, `reflection.py`,
`curiosity.py`) wraps its `run()` body with a start/finish pair
that captures the actual cost and effect counters:

```python
run_id = start_engine_run(db, engine=self.name, cycle=cycle)
# … existing engine body …
finish_engine_run(
    db, run_id, status="success",
    api_calls=1, tokens_in=N, tokens_out=M,
    chronicle_added=len(body.splitlines()),
    summary=body[:200],
)
```

Skip / fail paths set `status="skipped"` / `"failed"` with
`skip_reason` propagated.

### 2. New `caller` column on `api_calls` (P4)

Additive migration:

```sql
ALTER TABLE api_calls ADD COLUMN caller TEXT;
CREATE INDEX idx_api_calls_caller ON api_calls(caller);
```

`record_api_call(...)` gains a `caller: str | None = None`
parameter. ACT's three call sites pass `caller="act"`; engine call
sites pass `caller="discovery"`, `"reflection"`, etc. NULL is
back-compat for pre-v4.69 rows (~1,371 rows in the production DB).

Now `SELECT caller, SUM(input_tokens), SUM(output_tokens)
FROM api_calls WHERE caller IS NOT NULL GROUP BY caller` gives an
honest engines-vs-ACT cost breakdown.

### Known gap

`CuriosityEngine` calls `ActExecutor.execute(...)` internally. The
nested api_calls get `caller="act"` because ActExecutor doesn't
know it's nested under Curiosity. The engine_runs row for the
curiosity firing still reports the api_call_count correctly
(from `result.api_call_count`), but per-call attribution lumps
those calls under ACT.

Documented as a non-goal here; threading a caller hint through
`ActExecutor.execute(...)` is its own refactor and not needed for
the P1/P4 goal (one row per engine firing + a way to tell engine
calls from ACT calls in aggregate).

## Tests

`tests/test_engine_runs.py` — 12 new tests:

- Lifecycle: `start` creates running row; `finish` closes with
  counters; `finish` skipped records reason; `finish` failed
  records error; summary truncated to 200 chars
- Listing: filters by engine; orders newest-first
- Summary: counts by engine × status; empty case
- Caller column: `record_api_call` persists `caller`; NULL when
  omitted; `act` vs `reflection` distinguishable in aggregate

Full suite after v4.69: 747 passing (was 735, +12 new).

(13 pre-existing graph_store / graph_stress failures are unrelated
to this change — confirmed by a clean stash-then-test run against
the prior commit, and they involve a v4.61 wiki-projection path
that tries to resolve docs/adr paths under mind/wiki/. Filed for
follow-up; not blocking v4.69.)

## Non-goals (documented for the next ADR in the chain)

- **No backfill of pre-v4.69 rows.** `last_runs.json` stays for
  back-compat; pre-existing api_calls rows keep `caller=NULL`. The
  point is to start collecting honest data forward, not to invent
  the past.
- **No dashboard widget yet.** Same pattern as ADR 0072 → ADR 0073:
  ship the data layer first, then the surface. P1+P4 is the data;
  the widget is a follow-up (likely v4.70 alongside P2).
- **No threading `caller` through `ActExecutor.execute`.** The
  CuriosityEngine wrapper case is documented as a known gap; the
  engine_runs row captures the count without needing per-call
  attribution.
- **No deprecation of `ladder_outcomes.task_type` yet.** It's still
  written by the engines for compatibility with v4.51 widgets. The
  post-mortem flagged it as a redundant store; we'll remove it
  after the dashboard widget switches to engine_runs.
- **No fix for the 13 pre-existing graph_store test failures.**
  Confirmed pre-existing via stash diff; filed as separate
  follow-up.

## Why this shape

Why a new table instead of more columns on `ladder_outcomes`?
Because `ladder_outcomes` is per-rung-attempt; an engine firing
maps to one row in `ladder_outcomes` for the successful attempt
but zero rows on a skip. Plus the post-mortem found that NO
production engine firings landed task_type rows in
`ladder_outcomes` reliably — the helper was just being skipped.
Starting fresh in a dedicated table is cheaper than fixing the
incidental coupling.

Why `status="running"` as the open state? Because long-running
engines crashing mid-run is a real failure mode (the
ActExecutor-driven CuriosityEngine could hit a provider error
inside `executor.execute()`). A row left in "running" status is
visible to the operator as "engine X started at T and never
finished" — better than a missing row that requires reconciling
across three sources.

Why `caller` and not `phase`? Because the same `phase=PLAN` can
host multiple kinds of calls (engine, mutation_proposer, opus
PLAN call). `caller` names the subsystem, which is what cost
queries actually need.

Why don't engines also write `cost_usd` to the engine_runs row?
Because that would duplicate the v4.57 `cost_usd` work — pricing
lives in the price table, and aggregations recompute from tokens
× current prices. Future use of the column is reserved for
operator-set out-of-band cost (e.g. fine-tuned models with custom
pricing); for now it's null.
