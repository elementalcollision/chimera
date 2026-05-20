# Code Review: `chimera/core/kfm.py`

**Date:** 2025-05-19
**Reviewer:** Chimera (self-critical)
**File:** 99 lines, 1 function, 1 frozen dataclass, 2 module-level dicts
**Structural metrics:** 5 branches, 6 returns in `check_transition` (24 lines);
`TransitionResult` is a frozen dataclass with one computed property (`ok`).

---

## (a) What it does

Pure, stateless validation of the KFM entity lifecycle state machine.
Defines seven states (NEW → EXPERIMENTAL → CANDIDATE → STABLE → DEPRECATED →
ARCHIVED → KILLED), the legal forward-only transitions between them,
and which operator type (f/m/k/bootstrap) is authorised to request each
transition. The single public function `check_transition()` takes
`(from_state, to_state, operator_type)` and returns a `TransitionResult`
dataclass — never raises, never touches the DB. Called by every
`transition_entity()` in `chimera/memory/entities.py`.

---

## (b) Strongest design choice

**Table-driven state machine with immutable nested structures.**

`LEGAL_TRANSITIONS` uses `frozenset` values; `TRANSITION_AUTHORITY` uses
tuple keys. Both are impossible to mutate at runtime — no `.add()`, no
set-builder that could accidentally introduce a cycle. The validation
logic is a single 24-line function with 5 guard clauses, each returning
a distinct `reason` string so callers can distinguish "unknown_from_state"
from "operator_not_authorized" without pattern-matching on exception
types. I agree with this because the KFM protocol is verifiable by
inspection: read the two dicts, know every legal move. Unit-test coverage
is trivially computable: 7 × 7 × 4 = 196 possible invocations, of which
exactly 6 return `allowed=True`. No execution-dependent behaviour.

---

## (c) Weakest design choice

**`bootstrap` is a plain string in `OperatorType`, not a distinguished path.**

`bootstrap` appears in `OperatorType = Literal["f", "m", "k", "bootstrap"]`
and is checked via `operator_type != "bootstrap"`. This works, but any
caller that imports `OperatorType` can pass `"bootstrap"` — there's no
constant, no separate API, no flag on `TransitionResult` that says
"this was a privileged move." If a future mutation endpoint accepts
`operator` as free text, it can smuggle `"bootstrap"` through and the
state machine will accept it silently.

**Concrete alternative:** Remove `"bootstrap"` from `OperatorType`.
Add a second function `check_transition_unrestricted(from_state, to_state)`
that validates legal transitions only, skipping the authority check.
`ensure_current_plan()` in entities.py calls the unrestricted variant;
`transition_entity()` calls the restricted one. This makes the
privileged path a type-level distinction rather than a string match.

---

## (d) Suspected bug / footgun

**The `bootstrap` path is one `git grep` away from being callable from
any import site.**

In `entities.py:transition_entity()`, line 2 calls
`check_transition(entity.kfm_state, to_state, operator_type)` — it passes
whatever `operator_type` the caller supplied. There is no guard in
entities.py that says "reject bootstrap unless we're in the bootstrap
pathway." The KFM module trusts its caller completely.

I suspect this is latent: nothing passes `"bootstrap"` from a non-bootstrap
context *today*, but the type signature makes linters happy with any of
the four literals. A future mutation handler that takes `operator` as a
free-text field could trivially smuggle `"bootstrap"` through.

**Confirmation:** Call `transition_entity(conn, some_id, "ARCHIVED", "bootstrap")`
on any entity in any state. It won't raise. Then decide if that's a bug
or a feature. I lean bug — bootstrap should be scoped to `ensure_current_plan`.

---

## (e) Proposed ADR-sized refactor

**ADR-XXXX: Scope bootstrap to a dedicated code path.**

1. Remove `"bootstrap"` from `OperatorType`.
2. Rename `check_transition()` → `_check_transition()` (private).
3. Add `check_transition_authorized(from_state, to_state, op)` that
   validates the operator match (never matches `"bootstrap"` because
   it's no longer a valid literal).
4. Add `check_transition_unrestricted(from_state, to_state)` that does
   legal-transition validation only.
5. In entities.py, `transition_entity()` always uses the restricted
   variant. A new `bootstrap_entity()` function (called only by
   `ensure_current_plan`) uses the unrestricted variant.

Estimated diff: +15 lines, −5 lines, no behavioural change to existing
callers. The type-level distinction alone justifies the cost.
