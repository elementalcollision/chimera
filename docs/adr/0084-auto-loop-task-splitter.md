# ADR 0084 — Auto-loop task splitter integration (v4.65)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0082](./0082-task-splitter.md) shipped the task splitter as
an operator-manual surface (`chimera split <task>`). It explicitly
deferred ASSESS-phase auto-invocation until the heuristic could be
validated against more cases:

> Loop auto-integration into ASSESS is deferred until the heuristic
> is validated against more cases — the v4.46 escalation memory and
> ADR 0073 hot-signature alarm together provide enough feedback to
> tune before promoting to default-on.

With the heuristic now tested against the canonical 2026-05-19 burn
cases and shipping a confidence score, the natural next step is:
auto-detect bundled-shape tasks AFTER they've shown that they're
genuinely failing, and route a splitter call through the existing
mutation queue (same trust pattern as v4.39 `kill_entity` and
v4.46 escalation memory).

The trust-staircase rationale:
- **Heuristic alone** (cheap, no model call): can have false
  positives, fine because no spend.
- **Heuristic + escalation memory** (≥ N failures): the task has
  *actually* failed N times at this shape. Now spending $0.003 on
  a splitter call is justified.
- **Mutation queue** (operator approval): the agent proposes a
  rewrite; the operator decides. No silent INBOX mutation.
- **Explicit apply** (`chimera mutations apply <id>`): even after
  approval, the operator runs an explicit command to perform the
  rewrite. Matches the kill_entity workflow.

## Decision

### 1. New module `chimera/core/task_split_proposal.py`

```python
def task_split_enabled() -> bool
    # default OFF; opt in with CHIMERA_TASK_SPLITTER_ENABLED=1

def should_propose_split_for(
    conn, task_text, *, min_failures=3, min_confidence=0.5
) -> bool
    # heuristic ∧ escalation memory ∧ dedup

def propose_task_split(conn, task_text, subtasks) -> int | None
    # enqueue type="task_split" mutation

def apply_task_split(conn, mutation_id, inbox_path) -> dict
    # rewrite mind/INBOX.md: mark original [-], insert sub-tasks [ ]
```

`should_propose_split_for` is the gate. It returns True iff:
1. `is_splittable_shape(task_text).confidence ≥ 0.5` (heuristic
   from ADR 0082), AND
2. `task_escalations` has ≥ 3 rows whose signature overlaps the
   task's signature ≥ 50% (Jaccard) — i.e. the same task has
   failed 3+ times at the same shape, AND
3. no `task_split` mutation already targets this signature (status
   pending or approved).

The `min_failures=3` default is one above the v4.54 hot-signature
threshold (≥ 2). The hot-signature alarm fires at 2; the splitter
fires at 3. Gives the agent one more chance after the operator-visible
warning before the auto-splitter spends a model call.

### 2. New mutation type: `task_split`

Payload:

```json
{
  "signature": "<token-bag signature of original_task>",
  "original_task": "<full original task text>",
  "subtasks": ["<sub 1>", "<sub 2>", "<sub 3>", ...]
}
```

Lifecycle:
- **pending** (after `propose_task_split`)
- **approved** (operator runs `chimera mutations approve <id>`)
- **applied** (operator runs `chimera mutations apply <id>` — see §3)
- **failed** (apply found INBOX has been edited and the original
  task line is gone; marks mutation failed with a diagnostic)

### 3. `chimera mutations apply <id>`

New CLI subcommand. Currently supports `task_split` only (other
mutation types still have their own bespoke pipelines, e.g.
`chimera ontology --apply-kills`).

For `task_split`, rewrites `mind/INBOX.md`:
- Finds the line matching the original task text (tolerant: exact
  match OR 200-char prefix to survive minor whitespace differences)
- Marks it `[-]` with annotation: `[SPLIT v4.65: mutation #N →
  see N sub-tasks below]`
- Inserts each sub-task as a new `- [ ]` line at the same indent
  level, immediately after the original

If the original task line can't be found (operator edited INBOX
between approve and apply), the apply marks the mutation `failed`
with a diagnostic — non-destructive.

### 4. ASSESS hook (deferred to v4.65.1)

The current ADR ships the **infrastructure**: detection helpers,
mutation type, apply pipeline, full test coverage. The actual
ASSESS-phase wiring (call `should_propose_split_for` for each open
task each cycle and enqueue) is a one-line follow-up that depends
on the provider-resolution pattern.

Operator workflow today (v4.65):
```bash
# Manual trigger:
chimera split "<task text>"             # preview
chimera mutations list                  # see if it was queued
chimera mutations approve <id>          # approve
chimera mutations apply <id>            # rewrite INBOX
```

Operator workflow at v4.65.1 (when ASSESS hook lands):
```bash
export CHIMERA_TASK_SPLITTER_ENABLED=1   # opt in
# Mutations auto-queued by the agent each cycle for splittable
# hot signatures. Operator reviews + approves + applies.
```

## Tests

`tests/test_task_split_proposal.py` — 14 tests:

- Env gate (default OFF, truthy enables, falsy disables)
- `should_propose_split_for`: not splittable → False;
  splittable + < N failures → False; splittable + ≥ N failures →
  True; already-proposed signature → False
- `propose_task_split`: creates pending mutation with right shape;
  empty subtasks → None
- `apply_task_split`: rewrites INBOX correctly (original `[-]`,
  sub-tasks inserted); idempotent for already-applied; refuses
  unapproved; refuses non-task_split type; marks failed when
  original task missing from INBOX

Full suite after v4.65: 720 passing (was 706, +14 new).

## Non-goals

- **No ASSESS-phase auto-invocation yet.** Infrastructure-only
  release. The hook is a one-line follow-up in v4.65.1 once we
  validate the proposal queue behavior in a real session.
- **No automatic apply on approve.** Two-step (approve THEN apply)
  matches the v4.39 kill_entity pattern; operators see exactly
  what will happen before INBOX changes.
- **No re-detection on already-applied splits.** If a sub-task is
  itself splittable, the operator runs `chimera split` on it
  again; the heuristic doesn't track lineage.
- **No mutation-queue UI changes.** The dashboard's existing
  mutations widget displays task_split mutations the same way it
  displays other types — payload preview, status, reason.

## Why this shape

Why `min_failures=3` and not 2? Because the v4.54 hot-signature
alarm already surfaces ≥ 2 as a warning. Auto-splitting at 2 would
preempt the operator's review of why a task is failing — maybe the
task text just needs a typo fix, not a split. Three failures
means the operator has had two chances to see the alarm and chose
not to act; the auto-splitter is the third intervention.

Why route through the mutation queue instead of auto-applying?
Because INBOX is operator-owned. The agent rewriting it without
explicit operator consent is a trust step we haven't earned yet.
The mutation queue gives the operator a serializable audit log of
exactly what the agent wanted to do, with an explicit approve +
apply step.

Why a separate `apply` CLI verb instead of folding into `approve`?
Because the kill_entity workflow already established the
"approve in queue → apply via dedicated step" pattern. Operators
who learned that pattern at v4.39 already know what to expect at
v4.65. The two-step pattern also lets the operator review the
exact diff (via `chimera mutations show <id>`) between approval
and application.

Why tolerant prefix matching when finding the original task line?
Because the INBOX may have been minimally edited between propose
and apply (whitespace, line wrapping). A strict equality check
would over-fail. A 200-char prefix match catches the common
"operator added a clarifying note at the end" case without
risking matching the wrong task.
