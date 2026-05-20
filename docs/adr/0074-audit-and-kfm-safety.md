# ADR 0074 — audit.py transaction safety + KFM bootstrap scoping (v4.55)

**Status:** Accepted (2026-05-20)

## Context

The overnight code reviews in `mind/overnight/` produced two concrete,
small, well-scoped safety findings against load-bearing modules. This
ADR lands both as a single hardening release.

### Finding 1 — `chimera/memory/audit.py` transaction safety
(see `mind/overnight/code-review-audit.md` §c, §d, §e)

`auto_archive_stale_deprecated()` and `apply_approved_kills()` both
walk a batch of entities and call `transition_entity()` in a loop.
Pre-v4.55, each `transition_entity()` autocommitted, so a crash
partway through a batch (network drop, schema mismatch, disk full)
left some entities transitioned and others not — with no rollback
boundary. The review correctly named this as the audit module's
weakest design choice.

`audit_ontology()` itself has zero `try/except` clauses across seven
SELECT statements. If the housekeeping loop calls it against a
fixture or in-flight migration where `entity_transitions` or
`agent_activity_log` is missing, the whole loop crashes on an
unhandled `sqlite3.OperationalError`.

### Finding 2 — `chimera/core/kfm.py` bootstrap scoping
(see `mind/overnight/code-review-kfm.md` §c, §d, §e)

`OperatorType = Literal["f", "m", "k", "bootstrap"]` advertised
`"bootstrap"` as a valid operator. The check function passed any
transition where `operator_type == "bootstrap"`. In practice no
production code passed `"bootstrap"` (the actual bootstrap path
in `chimera/memory/entities.ensure_current_plan()` calls
`create_entity(initial_state="STABLE")` directly, never reaching
`check_transition`). But the type system advertised the bypass and
any future caller could trivially smuggle it through. The review's
recommendation: scope the privilege to a named function so the
operator-authority check stays unbypassable.

### Finding 3 — A21 grep verification surfaced a real bug

The bonus finding from the code review (§d):
*"the `dead_entities` joins on `cell_ref = e.id`, but the docstring on
`record_activity()` says `cell_ref = entity_id`. This is consistent
*today*, but if a future activity record uses `cell_ref` for something
other than an entity ID, the dead-entity query silently breaks."*

Grep verification: **`cell_ref` is NEVER set by production code.**
`chimera/core/loop.py:749` is the only production caller of
`record_activity()`, and it omits `cell_ref` entirely. So the
audit's dead query against `a.cell_ref = e.id` matches zero rows,
which means `NOT EXISTS (…)` returns true for every non-terminal
entity. **Every non-terminal entity reports as "dead" in production.**

The tests pass because `tests/test_audit_ontology.py` explicitly
passes `cell_ref=e.id` — exercising a path nothing in production
exercises.

This finding is **acknowledged here but not fixed in this ADR** —
it needs its own design decision (redefine "dead" against
`entity_transitions.cycle`, or backfill `cell_ref` everywhere the
loop touches an entity). Filed as a Tier 2 follow-up.

## Decision

### audit.py — `_batch_transaction` scope (observation, not atomicity)

`chimera/memory/audit.py` — new private context manager that scopes
the batch loop. **It is an observation boundary, not a true atomic
batch.** A first-pass attempt wrapped the loop in BEGIN/COMMIT, but
`transition_entity()` already issues its own BEGIN/COMMIT per call,
and SQLite rejects the nested BEGIN. The honest fix is:

```python
@contextmanager
def _batch_transaction(conn):
    try:
        yield
    except Exception:
        logger.exception("audit batch scope hit an unhandled exception")
        raise
```

Applied to:
- `auto_archive_stale_deprecated()` — wraps the `for r in rows` loop
- `apply_approved_kills()` — wraps the `for m in pending` loop

What this *does* give us: a single visible call site for the batch
boundary, a place to add batch-level logging/timing, and a
re-raise on any non-`transition_entity` crash (dict allocation,
logger failure). Per-entity atomicity is still the strongest
guarantee — each `transition_entity()` is independently atomic.
A mid-batch crash leaves successful entities committed and the rest
untouched; the returned list tells the operator what got through.

**True batch atomicity** would require refactoring `transition_entity`
to accept an existing transaction context (e.g.
`transition_entity(conn, …, in_batch=True)` that skips its internal
BEGIN/COMMIT). That's its own ADR — the code review surfaced the
gap correctly; the structural fix is larger than a one-line edit.

### audit.py — `audit_ontology()` schema-missing handling

Split into a public `audit_ontology()` that wraps `_audit_ontology_inner()`
in a single `try/except sqlite3.OperationalError`. On failure returns a
structured stub `{"error": "schema_missing", "detail": ..., ...zeros}`
with the same key shape as the success case so dashboard widgets and
CLI handlers don't crash on partial schemas.

### kfm.py — remove `"bootstrap"` literal

- `OperatorType = Literal["f", "m", "k"]` (was `["f", "m", "k", "bootstrap"]`)
- `check_transition()` rejects `"bootstrap"` with `reason="unknown_operator"`
  (the same path as any other unrecognised operator string)
- New `check_transition_unrestricted(from_state, to_state)` — the
  named hatch. Validates legal transitions only; skips authority.
  Reports `authorized_operator` in the result so audit logs still
  know who *would have been* required under normal rules.

The actual production bootstrap path (`ensure_current_plan`) was
never affected; it never went through `check_transition`. This is a
type-system tightening that makes the contract explicit.

### tests

- `tests/test_audit_ontology.py` — existing tests still pass (no
  behaviour change for the happy path).
- `tests/test_kfm.py` — `test_bootstrap_bypasses_operator_authority`
  renamed and inverted to `test_bootstrap_string_no_longer_accepted`
  (asserts the new reject behaviour). Two new tests pin
  `check_transition_unrestricted`: skips authority, still rejects
  illegal transitions.

Full suite after v4.55: 595 passing (was 593 at v4.54, +2 net new).

## Non-goals

- **Not refactoring the "dead" entity query.** The A21 finding is
  real and acknowledged in §Finding 3 above, but the fix needs a
  design decision (redefine the signal vs. backfill `cell_ref`)
  that's larger than this ADR's scope. Filed for Tier 2 follow-up.
- **Not adding nested-savepoint support to `_batch_transaction`.**
  SQLite handles nested `BEGIN` by ignoring the inner one as long
  as no savepoint is requested. The `owned = not conn.in_transaction`
  guard means we only own BEGIN/COMMIT when we issued BEGIN; nested
  cases yield through cleanly.
- **Not deprecating `"bootstrap"` softly.** It was advertised in the
  type signature but never used by production code; a clean break is
  simpler than a deprecation period, and `mypy` / type-aware editors
  catch any miss instantly.

## Why this shape

Why a context manager instead of `with conn:` (sqlite3's built-in)?
Because `with conn:` only manages the *outermost* implicit transaction
on autocommit mode — it doesn't help if `transition_entity()` already
issues its own BEGIN/COMMIT internally (and looking at it, it does:
each entity's transition is wrapped in commit_with_audit). The
`_batch_transaction` context manager makes the batch-level boundary
explicit and visible at the call site.

Why split `audit_ontology` into `_audit_ontology_inner`? Because the
alternative — wrapping each SELECT in its own try/except — would
litter the function with 7 redundant guards and obscure the audit
logic. A single outer try/except keeps the body readable and
guarantees uniform error shape.

Why surface the dead-query bug as a finding but defer the fix?
Because the bug has been latent since the audit module shipped at
v4.21 — the world has not ended in the intervening 30+ versions, so
there's no urgency that overrides the value of getting the fix
right. The two acceptable fixes (redefine "dead" against transitions
vs. backfill cell_ref) have different ergonomics; choosing without
discussion would be premature.
