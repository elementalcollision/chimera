# ADR 0147 — Commit-not-executed gate (the commit ACTION, not its message)

**Status**: Proposed (2026-05-30). Flip to Accepted after the next
commit-phase soak demonstrates the gate firing in-loop (re-prompting an
agent that staged but did not commit) and sleeping silently off-soak.

## Context

The v46 re-soak
(`mind/research/v46-resoak-scope-evasion-confirmed-problemB-isolated.md`,
branch `chimera-soak/v46-soakreport-2026-05-30-1929`) was a genuine rebuild
launched to confirm the scope_evasion commit-phase fix
([PR #180](https://github.com/elementalcollision/chimera/pull/180), the
on-disk-exists guard). It **confirmed that fix** — phase 2 reached the commit
task with zero scope_evasion firings — and, with that mask removed, isolated
the *second half* of the original v46 finding ("Problem B"):

> At cycle 156 the agent ran the gated test (4 passed), ran `git add` (files
> staged), and self-reported the **"Commit with a message starting with
> `[agent]`"** task `completed=True` — but **`git commit` never ran**. The
> deliverable sat staged-but-uncommitted. The external soft-sentinel
> (`soak_phase2_deliverable_landed`) correctly refused to converge, so phase 2
> idled to no signal until the operator stopped it.

The ACT completion chain in `chimera/core/act.py` is a sequence of gates that
each flip `completed=False` with a `finish_reason`:

- `ungrounded_citation` (ADR 0095), `scope_evasion` (ADR 0096/0109 + #180),
  `syntax_invalid` (ADR 0105), `import_shadowing` (B2) — all verify the
  **content** of work.
- `commit_message_diff_drift` (ADR 0115), `provenance_claim_invalid`
  (ADR 0118), `charter_file_count` (ADR 0116) — all verify the **message /
  diff of a commit that happened**.

**Every one of those assumes a commit occurred. None enforce that the commit
ACTION ran.** In a phase-2 (commit-only) soak the deliverable *is* the commit,
yet the only thing detecting its absence was the runner's *external*
soft-sentinel — which silently re-loops rather than feeding "you have not
committed" back to the agent in-cycle.

The agent diagnosed it itself. At cycle 158 the curiosity engine spawned
`q004: "Exploring commit compliance with strict constraints"` and wrote:

> Documentation-only compliance gets ~40% adherence. Trust-based prompts? Also
> ~40%. Deterministic hook enforcement achieves ~100%. The gap is not about
> better docs — it's about removing the ability to skip.

The phase-2 INBOX already stated the commit contract in **prose** ("git add
only stages… verify the commit exists with git log before you stop"). Prose is
the ~40%-adherence path. This ADR adds the deterministic gate.

## Decision

Add `check_commit_not_executed(task_text, worktree_root, base_ref="main",
head_ref="HEAD")` to the ACT completion chain, placed **before** the
message/diff/provenance commit gates (if no commit exists at all, "go run git
commit" is the actionable next step and those message-validators are moot —
each bails on a missing `[agent]` commit anyway).

The gate returns a one-item reason list (→ `completed=False`,
`finish_reason="commit_not_executed"`) only when ALL hold:

1. `worktree_root` is non-None. The call site passes
   `_import_shadow_scan_root()`, which returns the cwd **only inside a soak**
   (`CHIMERA_SOAK_RUN_ID` set) — so off-soak a normal `chimera run` is **never**
   forced to commit. This is the same soak-scoping the import-shadow and
   scope_evasion (#180) gates use.
2. The task demands an `[agent]` commit — `_task_demands_agent_commit`: the
   task text contains BOTH the `[agent]` subject token (the enforced
   commit-message marker, ADR 0122/0146) AND a `commit` imperative. Incidental
   `commit` mentions without `[agent]`, and the `[agent]` token without a
   commit verb, both pass (no fire).
3. No `[agent]`-subject commit exists in `base_ref..head_ref`
   (`git log --format=%s main..HEAD`, grep `^[agent]`).

This is the **inverse** of every other commit gate: they validate a commit
that happened; this catches one that was instructed but skipped. The
convergence criterion deliberately mirrors the runner's external
`soak_phase2_deliverable_landed` (≥1 `[agent]` commit in `main..HEAD`),
brought INSIDE the loop so the agent is re-prompted in-cycle instead of the run
idling.

### Conservative / fail-open (locked design constraint)

Charter: never raise. Any subprocess / seatbelt / non-repo error returns `[]`
(fail-open), matching its sibling gates. A plain (non-`[agent]`) commit — e.g.
the operator strip commit used by the genuine-rebuild knob — does NOT satisfy
the contract; only an `[agent]` commit does. Off-soak the gate is a hard no-op.

## Consequences

### Pros

- Closes the commit-action-vs-commit-message gap. The v46-B stall (staged,
  never committed, silent idle) becomes an in-loop `commit_not_executed`
  finish_reason with an actionable message ("run `git commit` and verify with
  `git log`").
- Deterministic enforcement of the contract the phase-2 INBOX previously
  stated only in prose — the ~40%→~100% adherence shift the agent's own
  research pointed at.
- Cheap: one `git log` subprocess, soak-scoped, no new ActResult field, no
  change to existing gates.

### Cons / honest disclosures

- **Trigger heuristic is harness-specific.** It keys on the literal `[agent]`
  token, which is the enforced commit-message marker across our soak charters.
  A charter wording the contract differently (e.g. "prefix `agent:`") would not
  trip the gate. Acceptable: the `[agent]` token is the contract (ADR 0122/0146)
  and charters use it verbatim; broadening the heuristic would raise the
  false-positive surface.
- **Does not catch "claimed commit, never even staged."** The gate fires on the
  absence of an `[agent]` commit regardless of staging, so it covers that case
  too — but its diagnostic message assumes the staged-but-uncommitted signature
  (the observed v46-B shape). The message is advisory; the fire condition is
  staging-agnostic.
- **Off-soak no-op by design.** A human-driven `chimera run` is never forced to
  commit. Commit enforcement is a soak-delivery concern only.

## Test coverage

`tests/test_act_commit_not_executed.py` — 12 tests: the trigger heuristic
(positive phase-2 task, negative build task, `[agent]`-without-verb, empty,
inflections), the off-soak `None`-root no-op, the non-commit-task pass, the fire
case (HEAD==main, no `[agent]` commit), the exact staged-but-uncommitted v46-B
signature, the satisfied case (an `[agent]` commit landed), the
non-`[agent]`-commit-does-not-satisfy case (the strip commit), and fail-open on
a non-repo dir.

## References

- [PR #180](https://github.com/elementalcollision/chimera/pull/180) — the
  scope_evasion on-disk guard whose confirmation surfaced Problem B.
- `mind/research/v46-resoak-scope-evasion-confirmed-problemB-isolated.md` —
  the re-soak capstone (this gate's motivating record).
- [ADR 0115](./0115-commit-message-diff-drift-detection.md),
  [ADR 0116](./0116-charter-file-count-enforcement.md),
  [ADR 0118](./0118-provenance-claim-validation.md) — the sibling commit gates
  this one precedes (they validate a commit that happened).
- [ADR 0146](./0146-pre-commit-scope-check.md),
  [ADR 0114](./0114-autonomous-delivery-contract.md) — the commit contract this
  gate hardens in-loop.
