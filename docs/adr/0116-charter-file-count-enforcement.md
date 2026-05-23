# ADR 0116 — Charter file-count enforcement (v4.116)

**Status:** Accepted (2026-05-23) — parallel layer to ADR 0112 (v4.112)
and ADR 0115 (v4.115)

## Context

ADR 0114 named the autonomous-delivery contract: the platform owes the
agent a falsifiable charter, and falsifiable means *structural*
verification, not "the panel reads it and decides if it likes the
diff". ADR 0112 (v4.112) gave the witness panel the INBOX charter's
prohibition / scope language. ADR 0115 (v4.115) caught one shape of
contract failure: commit message claims a path that isn't in the diff.

Soak v20-relaunch surfaced the *other* shape. Phase-2 INBOX charter:

```
CHARTER for phase 2:
  1. SCOPE: ONE new function, `check_ruff_claim_valid`, in
     `chimera/core/act.py`. ONE new test file,
     `tests/test_ruff_claim_invalid.py`. NO third file.
```

The agent's `[agent]` commit landed two files vs `main`:

1. `chimera/core/act.py`                      ✓ (enumerated)
2. `mind/research/ruff-claim-design.md`       ✗ (third file)

and was missing `tests/test_ruff_claim_invalid.py` entirely. The
v4.103 witness panel approved the diff — semantics looked plausible
to three LLMs reading file content. The panel sees natural language
and code; it does not natively reason "this commit has N files, the
charter enumerated M files, N != M, reject".

Nothing on the platform side compared the *committed file set*
against the charter's *enumeration*. The contract failed in a
structurally checkable way and the structural check did not exist.

## Decision

Add `chimera.core.witness.check_charter_file_count(task_text,
worktree_root, *, head_ref, base_ref) -> list[str]`, a structural
gate that runs alongside (not in place of) the semantic panel:

1. Extract a backtick-quoted, rooted file enumeration from the INBOX
   charter via `extract_charter_file_enumeration`, which reuses
   v4.112's `extract_task_charter` to scope to CHARTER /
   prohibition blocks.
2. Look at the head commit's message; if no `[agent]` prefix, return
   `[]` (operator commits are out of scope — same rule as v4.115).
3. Run `git diff --name-only base_ref..head_ref` and return every
   committed path that is neither in the enumeration nor covered by
   the `mind/research/*-remediation.md` auto-allow (soak_lib v2
   convention).

This is a separate layer from v4.112's semantic check, not a
replacement: the panel still reads the diff against the charter
prose. The structural check exists so that the gate can fire on a
*count or identity* mismatch regardless of what three LLMs decide
the code "looks like".

### Path extraction rules

To stay false-positive-safe, the enumeration recognizes ONLY:

* Backtick-quoted paths
* Rooted at a sanctioned top-level: `chimera/`, `tests/`, `mind/`,
  `docs/`, `state/`, `scripts/`
* Containing a file extension (`.py`, `.md`, `.sh`, …)

Bare paths in prose, unrooted backticked names (`` `foo.py` ``), and
backticked directory references (`` `chimera/core/` ``) are
deliberately not picked up. The cost of missing a charter that
enumerates files without backticks is a no-op; the cost of treating
prose ("the act.py module") as an enumeration is a wrong demotion.

### Soft-sentinel auto-allow

`mind/research/<topic>-remediation.md` is auto-allowed. This matches
the soak_lib v2 soft-sentinel pattern that lets a remediation cycle
write its own failure note without retroactively breaking the
charter that motivated the phase. Without this, every phase that
exercises the remediation path would trip the gate.

## Consequences

* New detector: `check_charter_file_count` returning the list of
  violating paths. Empty list means "no constraint or all clean";
  non-empty means "this commit exceeds the charter's file
  enumeration".
* Detector is added but **not yet wired** into the act / escalation /
  trust / remediation chain. Wiring is deliberately a separate PR
  (charter for this PR: two files + test). The wiring PR will add
  a `charter_file_count_violation` finish reason, a trust delta, an
  escalation entry, and a remediation hint — mirroring v4.115's
  shape.
* Soak v20 retro stays the motivating case; future soaks that
  enumerate files in their phase charter now have a structural floor
  beneath the panel's semantic ceiling.

## Non-decisions

* Do NOT auto-revert offending commits. Operator decides; the gate's
  job is to fire and demote, not to mutate the branch.
* Do NOT extend the path extractor to bare / unrooted paths. The
  operator convention is backticks + rooted prefix; broadening the
  extractor trades false-negatives (good) for false-positives (bad).
* Do NOT enforce non-file charter content (function names, line
  counts, named symbols) here. Semantic enforcement remains the
  panel's job.
* Do NOT count the charter's *required* files (missing-required is a
  separate detector class — v4.110/0112 territory). This detector is
  only the "too many files" half.

## See also

* ADR 0112 — Task-text charter extraction (semantic panel side)
* ADR 0114 — Autonomous-delivery contract (the named obligation)
* ADR 0115 — Commit-message vs diff drift (the lying-about-what-
  happened cousin)
