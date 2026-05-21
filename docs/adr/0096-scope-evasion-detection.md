# ADR 0096: Scope-evasion detection + explicit writable-scope grant

Status: Accepted
Date: 2026-05-20
Version: v4.82 (lands with v4.83 in the 4.83.0 release)

## Context

The 2026-05-20 v4 long-cycle soak surfaced a consistent failure shape
across 138 cycles. The phase-2 INBOX was unambiguous:

```
Implement the fix per the sketch. Most likely files:
  `chimera/tools/loop_guard.py` (if false-positive in detection)
  OR `chimera/core/act.py` (if correct detection but bad action).
```

The agent read the named source file and then produced
`mind/research/loop-abort-remediation.md` — a 34-line spec document —
rather than editing `chimera/tools/loop_guard.py`. The document
explicitly noted:

> "The `should_abort_loop()` function lives in the Chimera runtime
> (outside the `mind/` workspace — no `.py`/`.js`/`.ts` files found
> under `mind/`). This document serves as the specification for
> patching that function."

Three things went wrong:

1. The agent inferred that `mind/` was the boundary of its writable
   scope. The runtime never imposed that constraint — shell and
   code_exec can write under `chimera/`, `tests/`, `scripts/`, `docs/`.
2. The artifact-validation path (ADR 0093) didn't fire because the
   INBOX's `chimera/...` paths sit outside the trusted artifact roots
   (`state/`, `mind/`, `docs/`).
3. The agent's stop_reason was `stop`, the spec document existed, and
   ACT marked `completed=True`. Telemetry recorded a successful task.

Across four soaks the stall point has moved one layer deeper each time
(drift → displacement → phantom completion → reasoning/scope). v4.81's
plumbing is sound; the remaining failures are model-layer.

## Decision

Two coordinated changes in `chimera/core/act.py`:

### 1. Explicit writable-scope grant in `DEFAULT_SYSTEM_PROMPT_EXTRA`

Append a bullet that names the writable roots and explicitly tells the
model not to substitute a spec document for an edit of the named file.

The grant is part of the default system prompt so it reaches every
ACT-phase invocation, including engine-wrapped calls. We do not bury it
in INBOX seeds, because the failure pattern is the model's prior — not
the operator's phrasing.

### 2. `scope_evasion` finish_reason, parallel to `artifact_missing`

New helpers:

- `intended_code_paths(task_text)` — extract paths under
  `chimera/|tests/|scripts/` ending in a code/markup extension. Disjoint
  from `expected_artifacts()`'s roots (`state/|mind/|docs/`) so the two
  checks fire independently and report distinct failure modes.
- `check_scope_evasion(intended, history, write_targets)` — return the
  subset of intended paths that appear in neither any tool call's args
  nor the recorded `write_targets`. A real edit surfaces the path
  somewhere (shell command arg, code_exec snippet, post-write
  extraction); absence is the signal.

Wiring: in `ActExecutor._execute_inner`, after the grounding check
(ADR 0095), if the artifact and grounding checks both passed and any
intended code path was untouched, downgrade `completed=False` and set
`finish_reason="scope_evasion"`. Populates a new
`ActResult.unedited_paths` field for downstream telemetry.

`scope_evasion` joins `ESCALATING_FINISH_REASONS`. The next attempt at
the same task signature picks a higher tier under the v4.46 escalation
memory.

### Heuristic choice: "touched" = path appears in any tool arg

Cheaper than git-diff inspection and catches the actual failure shape.
A read (`cat chimera/x.py`) counts as engagement even if no write
follows — that is the intended behaviour: the deeper "read but
fabricate" pattern is the ADR 0095 grounding check's responsibility.
The two checks are designed to layer:

- Read the file, fabricate a spec under `mind/` → caught by ADR 0095.
- Read nothing, fabricate a spec under `mind/` → caught by ADR 0096.
- Read the file, write nothing → caught by ADR 0096.

## Consequences

- Tasks that name a code-root path will now require the agent to
  actually touch that path before completion is honoured. Operators
  should expect additional `scope_evasion` rows in `cycle_history`
  immediately after deployment until the prior is absorbed.
- The system prompt grows by one bullet (~60 tokens). Negligible
  against the per-cycle context.
- The "touched" heuristic accepts a path being mentioned in a tool arg
  as evidence of engagement. A pathological agent could namedrop the
  path in an unrelated shell command to defeat the check; that is the
  fabrication failure mode that ADR 0095 covers.
- Disjoint root sets between this ADR and ADR 0093 keep the failure
  modes independently attributable. A task that names both
  `mind/x.md` and `chimera/y.py` can fire either or both checks
  without overlap.

## References

- ADR 0093 — natural-language artifact validation (sibling check).
- ADR 0095 — synthesis citation grounding (paired remediation).
- soak v4 post-mortem — `mind/postmortems/soak-v4-2026-05-20.md`.
- Fixture worktree — `/Users/dave/chimera-soak-v4-2026-05-21-0037`.
- chimera/core/act.py — `intended_code_paths`, `check_scope_evasion`,
  `DEFAULT_SYSTEM_PROMPT_EXTRA`.
- tests/test_act_scope.py — regex + no-touch + fixture-replay tests.

## Amendment — 2026-05-20 (v4.85)

Soak v5 (`mind/postmortems/soak-v5-2026-05-20.md`, finding #5) exposed
two structural gaps in the v4.82 implementation:

1. **Gating to the clean-stop completion path only.** The scope-evasion
   check was wrapped in `if completed:` so it never ran on the
   max_rounds exit path. The soak v5 fixture "Implement the fix per
   the sketch. Most likely files: `X` OR `Y`" task burned its round
   budget without editing either named file and was recorded as
   generic `max_rounds`, hiding the diagnosable signal from escalation
   memory.

2. **Lenient "touched" semantics on the max_rounds path.** The loose
   `check_scope_evasion` heuristic accepts a path appearing in any
   tool arg as evidence of a touch. For tasks where the agent spent
   its budget *reading* the file (`cat chimera/...`) but never
   writing, this check returns clean. On the max_rounds exit we want
   the stricter signal: did anything actually land in `write_targets`?

### Changes

- New `check_scope_evasion_strict(intended, write_targets)` helper —
  write-targets-only semantics. Read commands don't satisfy.
- `ActExecutor` runs the strict check on the max_rounds exit. If the
  INBOX named code paths and `write_targets` contains none of them
  (and no missing artifacts already take the failure-mode slot), the
  `max_rounds` finish is demoted to `scope_evasion` with a pluralised
  reason `"scope evasion: named paths X, Y were not edited"`.
  `unedited_paths` is populated on the returned `ActResult`.
- Path extraction strengthened with an explicit backtick-only harvest
  pass (`_BACKTICK_CODE_PATH_PATTERN`). The legacy loose pattern
  already handled the multi-line "OR `X` OR `Y`" layout, parenthetical
  paths, and continuation-line wraps; the strict pass documents and
  guards that intent against future regex regressions. `intended_code_paths`
  returns the union.
- Negative case preserved: backticked symbol-like strings (e.g.
  `` `function_name()` ``) don't match because neither pattern admits
  a non-trusted-root prefix.

### Validation

- New tests in `tests/test_act_scope.py` cover the soak v5 OR-list
  fixture, parenthetical paths, continuation-line wraps, the negative
  symbol case, and the strict-check semantics.
- Pairs with v4.84 (ADR 0097): once v4.85 demotes a max_rounds finish
  to scope_evasion, the v4.84 remediation hint pipeline picks it up
  on the retry — the two ship together for soak v6.

### References (amendment)

- soak v5 post-mortem — `mind/postmortems/soak-v5-2026-05-20.md` §5.
- Fixture worktree — `/Users/dave/chimera-soak-v5-2026-05-21-0322`.
- ADR 0097 — post-escalation remediation hints (paired).
