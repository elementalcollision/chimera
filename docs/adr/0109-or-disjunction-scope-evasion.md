# ADR 0109 — OR-disjunction grouping for scope-evasion checks

**Status**: Accepted
**Date**: 2026-05-22
**Tag**: v4.105.0

## Context

Soak v12 (`state/long_cycle_v12_2026-05-22-1924.log`) fired
`scope_evasion` twice at `max_rounds=12` on tasks the agent had
correctly engaged with:

```
ACT: 'Implement the fix per the sketch. Most likely files:
`chimera/tools/loop_guard.py` (if the verdict was false-positive
and the heuristic needs adjustment) OR `chimera/core/act.py` (if
the verdict was correct...).' → scope_evasion (rounds=12, completed=False)

ACT: 'Write a regression test in `tests/test_loop_guard.py` (or
`tests/test_act_loop.py` as appropriate)...' → scope_evasion
(rounds=12, completed=False)
```

Both tasks name two candidate files joined by "OR" / "or". The agent
correctly satisfied each disjunction by picking one branch — and in
fact the work merged as `d614aaf` (writing `chimera/tools/loop_guard.py`
+ `chimera/core/act.py` + `tests/test_loop_guard.py`).

The bug: `intended_code_paths` extracts both branches of an OR-list
as required, and `check_scope_evasion_strict` (the variant used on
the max_rounds exit path) requires *every* intended path to appear
in `write_targets`. So picking one branch flagged the other as
"unedited" and demoted `max_rounds` → `scope_evasion`, masking the
real signal (slow convergence) with a false structural one.

### Hypothesis falsified along the way

An earlier hypothesis attributed this to `extract_target_paths`
failing to dig into quoted file paths inside `code_exec` code bodies
(per v4.92's `_WRITING_TOOL_NAMES` filter). Direct reproduction
showed the regex catches them fine — the path `chimera/core/act.py`
inside `Path('chimera/core/act.py').write_text(...)` is correctly
extracted. The actual root cause was upstream, in the *intent*
extraction not recognizing OR-disjunctions.

## Decision

Introduce `intended_code_path_groups(task_text) -> list[frozenset[str]]`.
Each group is a set of alternatives; the task is satisfied if AT
LEAST ONE path in the group is touched.

Grouping rule: for each adjacent pair of path matches in the task
text, inspect the gap between them. If the gap contains a bare
`or` / `OR` token (word-bounded) AND no sentence break, the paths
belong to the same group. Transitive closure handles `X or Y or Z`
chains. A sentence break (`.!?` followed by whitespace + capital
letter, or a blank line) forces separate groups.

`check_scope_evasion` and `check_scope_evasion_strict` are extended
to accept `Sequence[str | frozenset[str]]`. A `str` is treated as a
singleton group, preserving back-compat for the INBOX-honesty and
remediation callers that pass flat lists for other purposes.

The two ACT-phase call sites — round-level (`act.py:~1454`) and
max_rounds exit (`act.py:~1883`) — switch to
`intended_code_path_groups`.

## Consequences

- Soak-v12-shape tasks ("X OR Y") no longer false-positive on
  `scope_evasion`. The agent is free to pick the right file.
- The strict at-max_rounds check now correctly attributes the v12
  failures to `max_rounds` (slow convergence) rather than
  `scope_evasion` (structural). That's the right signal — agent
  needed more rounds, not better aim.
- The `intended_code_paths` flat function is preserved as-is for
  INBOX-honesty and remediation, where "name all candidate paths"
  is the right semantic.
- Reporting (`unedited_paths` on `ActResult`) is unchanged in shape;
  unsatisfied groups contribute *all* their candidate paths so the
  operator sees the full disjunction.

## Non-goals

- Not changing `_WRITING_TOOL_NAMES` (v4.92). Confirmed correct.
- Not changing the post-tool `extract_target_paths` regex.
  Confirmed it handles quoted paths inside `code_exec` bodies.
- Not detecting "actually changed on disk." Tool-arg inspection
  remains the right layer.

## Tests

- `tests/test_act_scope.py` adds 13 cases covering:
  - OR-disjunction grouping (uppercase, lowercase-in-parens, chains)
  - Sentence-break boundary (forces separate groups)
  - "X and Y" (forces separate groups)
  - Either-branch satisfies, neither-branch is evasion
  - Mixed groups (required + optional in the same task)
  - Back-compat: flat `list[str]` callers still work

## Lessons

A detection heuristic that extracts "what the task names" must
distinguish *conjunctive* requirements (all needed) from
*disjunctive* alternatives (any one needed). The legacy flat-list
output conflated both. The brief proposing this fix initially
mis-attributed the cause to a lower layer (`extract_target_paths`);
reproducing the proposed bug directly falsified that hypothesis
within five minutes — without the existing soak v12 log file
intact, the chip would have shipped against the wrong layer.
