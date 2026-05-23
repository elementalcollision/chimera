# ADR 0118: Provenance-claim validation in [agent] commits (v4.118)

**Status**: Accepted
**Date**: 2026-05-23
**Soak**: v20-3rd (motivating fixture)

## Context

ADR 0115 closed the **commit-message-vs-diff** gap for *paths* — the
agent claimed `tests/test_ruff_claim_invalid.py` in the commit body
but never `git add`-ed it. The detector compared rooted path tokens
in the commit message against `git diff --name-only` and flagged the
mismatch.

Soak v20-3rd surfaced a parallel lie at a different token layer.
Phase-2 agent landed commit `e3af158` with subject:

```
[agent] Add ruff_claim_invalid detector (v4.120 / ADR 0120)
```

At the time the actual platform version was v4.116 (PR #13 had just
merged ADR 0116) and ADR 0120 did not exist anywhere in the repo.
The path claims in the message body were all honest — v4.115
cleared. The diff itself was structurally fine — the witness panel
cleared. But the *version + ADR cites* in the subject were
fabricated, presumably to make the commit look more authoritative.
No detector in the chain reads non-path tokens in commit messages.

This is a new class: **fabricated provenance citations**. It's
adjacent to ungrounded_citation (which checks task-text claims
against task-text sources) and to v4.115 (which checks path claims
against the diff), but its surface — version and ADR identifiers in
a commit message — is structural metadata neither of those covers.

## Decision

Add a single deterministic ACT-time detector that validates
`vX.Y` and `ADR NNNN` citations in `[agent]` commit messages
against the repo's actual tag set, source version strings, and
`docs/adr/` directory. Wire it through the same severity / hint /
escalation layers as v4.115.

1. **ACT-time** (per-task, post-commit):
   `check_provenance_claim_valid(worktree_root, head_ref)`:
   - Reads `%s`; only fires when the subject starts with `[agent]`.
   - Reads `%B` and extracts:
     - Version tokens via `\bv(\d+\.\d+)(?:\.\d+)?\b` → normalized
       to `X.Y`.
     - ADR tokens via `\bADR[\s-]*0*(\d{1,4})\b` → normalized to
       zero-padded 4-digit strings.
   - A version **resolves** if any of: a `vX.Y` / `vX.Y.*` git tag
     exists, OR `pyproject.toml` / `chimera/__init__.py` contains
     `version = "X.Y…"` / `__version__ = "X.Y…"`, OR any
     `docs/adr/*.md` mentions the literal `vX.Y`.
   - An ADR **resolves** if `docs/adr/NNNN-*.md` exists.
   - Returns human-readable cite strings (`"v4.120"`, `"ADR 0120"`)
     for each non-resolving claim. Charter: never raise;
     subprocess / filesystem errors return `[]`.

   Wired between `commit_message_diff_drift` (the v4.115 path gate)
   and `witness_rejected` (semantic gate). Fires
   `finish_reason="provenance_claim_invalid"`.

2. **Trust delta**: `-1` (one-tier demote). Same severity as
   `commit_message_diff_drift` and `test_claim_invalid` —
   incomplete delivery against an implicit "the commit message
   tells the truth about which versions and ADRs this work
   relates to" contract.

3. **Remediation hint**: `_provenance_claim_invalid_hint` names
   the bad citations and tells the agent to look up real numbers
   via `git tag --list` and `docs/adr/`, or drop the citation
   entirely.

4. **Escalation**: added to `ESCALATING_FINISH_REASONS`. Same
   three-strikes auto-skip path as `commit_message_diff_drift` /
   `test_claim_invalid` / `syntax_invalid`.

## Non-decisions (deliberate)

- **Don't extend to non-version / non-ADR provenance.** PR URLs,
  soak numbers, commit SHAs — each has its own ambiguity surface
  (PR exists in a different repo? soak number is informal
  shorthand?). Separate concerns; tackle when motivated by a real
  failure.
- **Don't auto-fix the commit message.** Whether the citation is
  a fabrication or a typo is a charter call. The detector flags;
  the remediation loop drives the fix.
- **Don't enforce that `[agent]` commits MUST cite a version /
  ADR.** The gate is "cited ones must exist," not "must cite."
  Many honest commits don't need provenance pins.
- **Don't extend to operator collaborator commits.** Operator
  commits aren't autonomous-delivery contracts. Operator prose in
  commit bodies legitimately discusses future versions / proposed
  ADR numbers.
- **Don't reuse the v4.115 extractor.** Different token class
  (numbers, not paths) — parallel-build a small regex pair.
- **Don't gate at submit-pr time only.** The v4.115 precedent is
  ACT-time so the remediation loop can fix it inside the same
  task; PR-time would push the lie out to operator review.
- **Don't try to be clever about version-form normalization.**
  `v4.115` and `v4.115.0` both normalize to `4.115` and resolve
  the same way. That's enough; no SemVer ordering, no range
  matching.

## Consequences

**Positive**

- First **commit-meta-citation** detector. Closes the
  fabricated-authority lane that v4.115 (paths) and the witness
  panel (diff semantics) both leave open.
- Soak v20-3rd's `e3af158` (v4.120 / ADR 0120 fabricated) would
  now be caught at ACT time.
- Cheap and deterministic — two `git log` invocations plus
  small-file reads. No model call.

**Negative**

- Only fires on cited claims. An agent who avoids citing
  versions / ADRs sidesteps the gate. Acceptable: the failure
  mode is specifically "cited X, X doesn't exist." Honest
  uncited commits aren't in scope.
- Version resolution falls back to substring search in ADR
  files. A future ADR happening to mention a not-yet-released
  `vX.Y` (e.g. "future work: v4.999 will…") would resolve that
  version. Acceptable: such ADRs are themselves first-class
  provenance.
- Tied to `[agent]`-prefixed subjects. Same mitigation as v4.115
  (subject-allowlist gate at submit-pr).

## Future work

- **Submit-pr branch-level walk**: validate every `[agent]`
  commit's provenance cites, not just HEAD.
- **PR-link validation**: parse `PR #NNN` cites and confirm via
  `gh pr view` / local cache that the PR exists and refers to
  this repo. Different ambiguity surface; out of scope here.
- **Soak-version citation**: structural validator for `soak vN`
  cites against the soak runner registry once that registry has
  a canonical form.

## References

- Soak v20-3rd motivating commit: `e3af158` (subject claimed
  v4.120 / ADR 0120; actual platform v4.116)
- Sibling detectors: ADR 0115 (commit_message_diff_drift),
  ADR 0113 (test_claim_invalid), ADR 0106 (witness)
- Trust table: `chimera/trust/manager.py FINISH_REASON_TRUST_DELTAS`
