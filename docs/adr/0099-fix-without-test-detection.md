# ADR 0099: Fix-without-test detection

**Status:** Accepted
**Date:** 2026-05-22
**Version:** v4.90
**Related:** ADR 0096 (scope-evasion), ADR 0097 (post-escalation remediation),
ADR 0098 (ping-pong loop detection), soak v6 post-mortem
(`mind/postmortems/soak-v6-2026-05-22.md`).

## Context

Soak v6 was the headline win across six soaks: the agent edited
`chimera/tools/loop_guard.py` for the first time, shipping a real
`detect_ping_pong()` function (+43 lines) that complemented the
existing degenerate-loop guard. The recovery chain v4.82 → v4.86
demonstrably worked end-to-end.

But the deliverable was *incomplete*. The agent never wrote the
matching regression test in `tests/test_loop_guard.py`. The escalation
table partially caught this via `artifact_missing` (when the task
named a `tests/...` path under backticks), but the broader pattern —
"agent modifies chimera/ source without writing a corresponding test
file" — was not directly detected.

The six-soak arc, viewed end-to-end:

| Layer | Frontier closed |
|---|---|
| 1. Orchestration (soak v1–v2) | Can the runner stay up for cycles? |
| 2. Plumbing (v3) | Can tools dispatch correctly? |
| 3. Reasoning (v4) | Can the agent name the right scope? |
| 4. Recovery (v5) | Can the runtime detect a failed cycle? |
| 5. Tooling (v6 shell allow-list) | Can the agent run the commands it needs? |
| 6. **Completeness (v6 gap)** | **Can the agent ship a *complete* deliverable?** |

Layer 6 is the new frontier. The agent can write source; it now needs
to write the test that proves the source works.

## Decision

Add `fix_without_test` as a new `finish_reason` enum value, detected
on the ACT clean-stop completion path *after* the existing scope
checks. The detector is loose-heuristic by design (same shape as
`check_scope_evasion`): a path is "touched" if it appears in any
tool-call arg value or in `write_targets`.

Detection criterion (`chimera.core.act.check_fix_without_test`):

1. Scan all tool-call args + `write_targets` for paths matching
   `chimera/**/*.py`.
2. Exclude `chimera/_version.py` and `chimera/__init__.py` (touching
   these alone is bookkeeping, not a "fix").
3. If any qualifying source path is found, scan the same blob for
   paths matching `tests/(<subdir>/)?test_<stem>.py`.
4. **Yes-source-no-test** → downgrade `completed=True` to `False`
   with `finish_reason="fix_without_test"`, populate
   `untested_fix_paths`.

This composes cleanly with:

- **v4.84 (ADR 0097) remediation:** `_fix_without_test_hint` derives
  the corresponding test path from the chimera/ source name and tells
  the model "use code_exec to create `tests/test_<stem>.py` with at
  least 3 test cases covering normal/edge/threshold behaviour".
- **v4.84 three-strikes auto-skip:** `fix_without_test` is added to
  `ESCALATING_FINISH_REASONS` so the same task that produces three
  consecutive untested fixes skips with a chronicle warning instead
  of looping forever.

## Why "yes-yes-no" instead of stricter mutation evidence

A stricter detector — "the agent ran `sed -i` or wrote with mode='w'"
— would have lower false-positive rate but more code, more brittleness
to new tool shapes (write tools, IDE-style edit tools we may add
later), and depends on the agent's exact command shape rather than
its observable intent. The loose-heuristic shape matches the existing
scope-evasion check and produces an actionable hint either way: even
on a borderline false positive (read-only `cat chimera/foo.py`), the
remediation "write a regression test for foo" is harmless and on-flow.

We prefer false positives over false negatives at this stage: soak v6
proved the agent *can* ship code; the cost of asking it to also ship
tests when it merely read is low, while the cost of letting a bare
fix ship without tests compounds into a maintenance liability.

## Consequences

- Tasks that intentionally only *read* chimera/ source (audits, doc
  generation pointed at code) may falsely trip the detector on the
  clean-stop completion path. Mitigation: the v4.84 remediation hint
  is benign in that case, and a three-strikes skip surfaces it to the
  operator before budget burns.
- The detector does not fire on `max_rounds` exit — that path is
  already handled by the scope-evasion-strict check (v4.85). Adding
  it there would double-tag the same failure.
- Net new failure mode in the table: layer 7 (completeness) of the
  six-soak hardening arc, opened by this ADR for closure in v4.91+.

## References

- soak v6 post-mortem, Failure B section.
- `chimera/core/act.py`: `check_fix_without_test`, completion path.
- `chimera/core/remediation.py`: `_fix_without_test_hint`.
- `chimera/core/escalation.py`: `ESCALATING_FINISH_REASONS`.
- `tests/test_act_completeness.py`: 16 cases covering normal,
  exclusion, soak v6 fixture, hint derivation.

---

## Amendment — v4.91 (2026-05-22)

Soak v7 surfaced a critical false-positive in v4.90: the detector
scanned `tool_call_history` arg values for chimera/X.py paths. This
falsely fired on READ operations — `cat chimera/core/act.py`,
`read_file(...)`, and even task descriptions echoed through tool args.

Phase 1 of soak v7 was an investigation phase that asked the agent
to READ several chimera/ files. Every one of those tasks escalated as
`fix_without_test`, three-strikes auto-skipped, and phase 1 never
produced the READY-FOR-REMEDIATION sentinel. `fix_without_test=4` in
the escalations table with zero chimera/ writes and zero tests/ writes
is the diagnostic signature.

### v4.91 fix

`check_fix_without_test` now inspects ONLY `write_targets` — paths the
agent actually wrote during the task. Reading a chimera/ source file
no longer counts as a fix. The `tool_call_history` parameter is kept
for ABI compatibility but ignored.

The v4.90 unit tests had constructed `tool_call_history` with paths
in tool args and `write_targets=[]` — which passed under v4.90's
arg-scanning behavior but would have hidden the false-positive. v4.91
rewrites the test suite to populate `write_targets` directly, matching
the real wiring shape, and adds three new regression cases for the
v7 false-positive pattern:

- `test_v4_91_reading_chimera_source_does_not_flag`
- `test_v4_91_inbox_quoted_path_does_not_flag`
- `test_v4_91_write_to_mind_does_not_flag_even_if_args_mention_chimera`

### Lesson

The "loose heuristic" comment in the v4.90 docstring ("a path is
'touched' if it appears in any tool call arg value or in
write_targets") was the bug, not the fix. Looseness in scope_evasion
is fine — it errs toward catching the model when it's near the right
file but writing somewhere else. Looseness in fix_without_test is
catastrophic — reading is by far the more common operation, so a
read-positive detector floods escalations and starves the agent of
progress via three-strikes.

The two detectors look superficially similar but have inverse risk
profiles. They should not share heuristics.
