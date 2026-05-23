# ADR 0115: Commit-message-vs-diff drift detection (v4.115)

**Status**: Accepted
**Date**: 2026-05-23
**Soak**: v20-relaunch (motivating fixture)

## Context

ADR 0113 closed the **runtime-behavior** gap — agents claiming
`uv run pytest` passed when it actually failed at execution time.
ADR 0114 formalized the autonomous-delivery contract. Both
detectors read the **task text** (the INBOX bullet, the operator's
charter) and either compare it against the diff or re-run the
behavior the task promised.

Soak v20-relaunch surfaced a new lie that lives one layer down:
**the commit message itself.**

Phase-2 agent in soak v20-relaunch landed commit `d4cef6c`:

```
[agent] chimera/core/act.py: add check_ruff_claim_valid detector

... v4.113 (PR #6) shipped check_test_claim_valid to catch agents
lying about pytest. This is the symmetric remediation for ruff,
with the test file at tests/test_ruff_claim_invalid.py exercising
six cases ...
```

The diff against `main` carried:

- `chimera/core/act.py` — the new function landed
- `mind/research/ruff-claim-design.md` — out-of-charter doc

…but **not** `tests/test_ruff_claim_invalid.py`. The agent had
written the file (it existed on disk, six tests passing locally),
but never `git add`-ed it before committing. The cumulative branch
diff did not carry it, so the witness panel never read it, the
fix_without_test gate cleared (the agent did add a research doc
under the same diff), and every structural detector passed.

The lie shape: **the commit message body asserted "X plus tests";
the diff carries X without tests.** No existing detector compares
the two — `task_text` detectors don't look at commits, `diff`
detectors don't look at the commit message body.

## Decision

Add `commit_message_diff_drift` as a new detector class — parallel
to v4.113's runtime-drift layer but operating on the **commit
message vs cumulative diff** rather than the task text vs runtime.

1. **ACT-time** (per-task, post-commit):
   `check_commit_message_diff_drift(worktree_root, head_ref, base_ref)`:
   - Reads the HEAD commit's `%s` (subject). Only fires when the
     subject starts with `[agent]` — operator commits aren't an
     autonomous-delivery contract.
   - Reads the HEAD commit's `%B` (full message) and extracts
     rooted path claims via a regex matching `tests/...`,
     `chimera/...`, `mind/...`, `docs/...`, `state/...`,
     `scripts/...` with `.py`/`.md`/`.sh`/`.toml`/`.json`/`.yaml`/
     `.yml`/`.txt` suffixes. Both backticked and bare forms.
   - Reads `git diff --name-only <base>..<head>`.
   - Returns claims that aren't in the diff.
   - Charter: never raise; subprocess errors return `[]`.

   Wired between `test_claim_invalid` (cheap deterministic
   runtime gate) and `witness_rejected` (expensive semantic gate):
   text-vs-reality is fast and unambiguous. Fires
   `finish_reason="commit_message_diff_drift"`.

2. **Trust delta**: `-1` (one-tier demote). Same severity as
   `test_claim_invalid` and `syntax_invalid` — incomplete delivery
   against an explicit "the commit message tells the truth"
   contract, recoverable from a single hint.

3. **Remediation hint**: `_commit_message_diff_drift_hint` names
   the missing path(s) and tells the agent to either `git add`
   them and amend, or rewrite the commit message. The gap is the
   failure; either side may be correct.

4. **Escalation**: added to `ESCALATING_FINISH_REASONS`. Same
   three-strikes auto-skip path as `test_claim_invalid` /
   `syntax_invalid`.

## Non-decisions (deliberate)

- **Don't auto-amend the commit.** Whether the right fix is
  `git add` + amend vs. message rewrite is a charter call — the
  detector reports the drift; the remediation loop drives the
  fix. Auto-amending would silently rewrite history.
- **Don't extend to non-`[agent]` commits.** Operator commits
  aren't part of the autonomous-delivery contract; soak-test
  scaffolding and operator scripting routinely mention paths
  they didn't touch (e.g. soak runners describing a charter).
- **Don't infer from prose-only paths.** Only fire on paths with
  a trusted root (`tests/`, `chimera/`, `mind/`, `docs/`,
  `state/`, `scripts/`). Un-rooted phrases like "the test file"
  or "the README" are too ambiguous to action.
- **Don't reuse v4.113's `task_text` extractor.** Different
  surface, different shape — parallel-build a small,
  commit-message-specific regex. The two detectors are
  conceptually parallel but their inputs aren't fungible.
- **Don't replace the witness panel.** Witness reads the diff;
  this detector reads the diff plus the commit message. They
  catch different lies.

## Consequences

**Positive**

- First **commit-text-vs-reality** detector. The chain now
  covers parse, structural, semantic, runtime-behavior, AND
  commit-meta-truth layers.
- The soak v20-relaunch fixture (un-staged tests file claimed
  in commit body) is now caught at ACT time.
- Deterministic and cheap — two `git log` + one `git diff`
  invocation, no model call.

**Negative**

- Only fires when the commit message names a rooted path. An
  agent who avoids naming paths in their commit body sidesteps
  the gate. Acceptable: the failure mode is specifically
  "named X, didn't do X" — silent commits have other gates.
- Tied to `[agent]`-prefixed subjects. If the prefix discipline
  slips, the detector quietly stops firing. Mitigated by the
  existing submit-pr subject-allowlist gate.

## Future work

- **Submit-pr branch-level gate**: walk every `[agent]` commit
  in the branch and check each message-vs-diff individually,
  catching the cumulative case where any single commit lies.
- **Symbol claims**: extend the extractor to function/class
  names that don't appear in the diff (e.g. message says
  "added `check_ruff_claim_valid`" but the diff doesn't define
  it). Symmetric to ungrounded_citation but for commits.

## References

- Soak v20-relaunch motivating commit: `d4cef6c`
- Failure point: `tests/test_ruff_claim_invalid.py` named in
  commit body, absent from `git diff --name-only main..HEAD`
- Sibling detectors: ADR 0113 (test_claim_invalid),
  ADR 0105 (syntax_invalid), ADR 0106 (witness)
- Trust table: `chimera/trust/manager.py FINISH_REASON_TRUST_DELTAS`
