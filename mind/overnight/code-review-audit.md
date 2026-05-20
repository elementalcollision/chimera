# Code Review: `chimera/memory/audit.py`

**Date:** 2025-05-19
**Reviewer:** Chimera (self-critical)
**File:** 406 lines, 5 functions, 0 classes
**Structural metrics:** `audit_ontology` (141L, 0 branches, 7 SQL),
`auto_archive_stale_deprecated` (65L, 4B, 1 SQL),
`propose_kill_archived` (67L, 5B, 1 SQL),
`apply_approved_kills` (47L, 4B, 0 SQL),
`reanchor_history` (45L, 3B, 1 SQL)

---

## (a) What it does

Drives the entity lifecycle termination pipeline. `audit_ontology()`
queries the SQLite DB for stale (non-terminal entity stuck in state),
dead (no recent activity), and re-anchored (STABLE → DEPRECATED via K)
entities. `auto_archive_stale_deprecated()` promotes aged DEPRECATED
entities to ARCHIVED via the K-operator. `propose_kill_archived()` and
`apply_approved_kills()` implement the two-phase ARCHIVED → KILLED path
(ADR 0046), where the operator must approve each kill mutation before
it's applied. `reanchor_history()` buckets K-operator demotions for
trending. All five functions receive an open `sqlite3.Connection` and
operate in the caller's transaction context.

---

## (b) Strongest design choice

**Two-phase kill with dedup against pending mutations.**

`propose_kill_archived()` checks `list_mutations(conn, type="kill_entity", status="pending")`
and skips entities that already have an unapproved kill mutation. This
prevents queue-flooding when the audit runs every cycle — same entity,
same proposed kill, only one pending mutation ever. `apply_approved_kills()`
then walks *approved* mutations only, so the operator has an explicit
review step. I agree with this because it separates the automated
detection (safe to run every cycle) from the automated execution
(gated by explicit operator consent). The dedup logic is simple and
correct: it reads all pending mutations into a set and checks membership
before enqueuing. O(n) in pending mutations, which is fine since the cap
is 25.

---

## (c) Weakest design choice

**No transaction safety: every function assumes the caller manages the
transaction, but none document what they expect.**

All five functions read/write on a bare `conn` — none issue `BEGIN` or
`COMMIT`. The docstrings don't state whether the caller should open a
transaction beforehand, or whether each function expects to be called
within an existing transaction. `auto_archive_stale_deprecated()` calls
`transition_entity()` (which *does* manage its own `BEGIN`/`COMMIT`) in a
loop — this means each archived entity gets its own transaction, so if the
loop crashes partway through, some entities are archived and some are not,
with no partial-rollback safety. `apply_approved_kills()` has the same
pattern: each call to `transition_entity()` is independently committed.

**Concrete alternative:** Add a `with conn: context = atomic_write(conn)`
decorator or context manager to `auto_archive_stale_deprecated()` and
`apply_approved_kills()` that wraps the entire batch loop in a single
transaction. If any transition in the batch fails, the whole batch
rolls back — no partial archiving. Document explicitly on all five
functions: "This function expects to be called within an active
transaction, OR will open one if none is active."

---

## (d) Suspected bug / footgun

**`audit_ontology()` has zero branches in its function body — all 7 SQL
queries are independent SELECTs that never check for a missing DB schema.**

The function runs 7 separate `conn.execute()` calls. If the `entities`
table is empty, `SELECT COUNT(*) AS n FROM entities` returns 0 — fine.
But if the `entity_transitions` or `agent_activity_log` tables are
missing (e.g. a migration that hasn't run yet, or a test fixture with
partial schema), the function will raise an unhandled `sqlite3.OperationalError`.
There is no `try/except` anywhere in the function body. Because
`audit_ontology()` is called from the main loop's housekeeping phase,
a missing table would crash the entire loop.

I also suspect a subtler issue: `dead_entities` joins on `cell_ref = e.id`,
but the docstring on `record_activity()` in entities.py says
`cell_ref = entity_id`. This is consistent *today*, but if a future
activity record uses `cell_ref` for something other than an entity ID
(e.g. a session ID), the dead-entity query silently breaks — it would
identically report that entity as dead because no activity matches.

**Confirmation:** Drop the `entity_transitions` table in a test fixture,
call `audit_ontology()`, confirm it raises `OperationalError` instead of
returning a graceful error dict. Also confirm that the `dead` query uses
`cell_ref = e.id` — grep for all `record_activity` call sites and check
they pass an entity ID as `cell_ref`.

---

## (e) Proposed ADR-sized refactor

**ADR-XXXX: Wrap batch archive/kill operations in a single transaction.**

1. Add a `conn_writer` context manager (or use sqlite3's
   `conn.__enter__`/`__exit__` which manages transactions):
   ```python
   @contextmanager
   def _batch_transaction(conn: sqlite3.Connection):
       conn.execute("BEGIN")
       try:
           yield
           conn.execute("COMMIT")
       except Exception:
           conn.execute("ROLLBACK")
           raise
   ```
2. In `auto_archive_stale_deprecated()`, wrap the `for r in rows` loop
   in `with _batch_transaction(conn):`.
3. Same for `apply_approved_kills()`.
4. Add a `try/except sqlite3.OperationalError` in `audit_ontology()` that
   returns a structured error dict with `{"error": "schema_missing", "detail": ...}`
   instead of crashing.

Estimated diff: +20 lines, −0 lines, no behavioural change to callers
who already use their own transaction wrapper (nesting is a no-op in
SQLite as long as a SAVEPOINT isn't needed, which it isn't here).
