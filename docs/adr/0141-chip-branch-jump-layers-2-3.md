# ADR 0141 — Chip-branch-jump prevention, Layers 2 and 3

**Status**: Proposed (2026-05-25). Flip to Accepted after ≥5 sessions
with no chip-branch-jump papercut recurrence.

## Context

Chip sessions spawned via `mcp__ccd_session__spawn_task` occasionally
check out their feature branch into the operator's main worktree
(`/Users/dave/uberagent`) instead of a fresh sibling worktree. Each
occurrence costs the operator a stash + checkout + worktree-add +
stash-pop cycle. The pattern was hit 3+ times during the v4.114.0
development chapter (PRs #41, #49, #52).

**Layer 1** (PR #46): `chimera doctor` emits a `warn` for the
`worktree_branch_drift` check when cwd is the git toplevel AND HEAD is
not `main`. Reactive — fires only when the operator voluntarily runs
`doctor`.

This ADR completes the composed-tier 3-layer detection stack chartered
by [ADR 0114](./0114-autonomous-delivery-contract.md).

## Decision

| Layer | Surface | Posture | Effect |
|---|---|---|---|
| 1 (PR #46) | `chimera doctor` | reactive | warn check |
| **2 (this PR)** | `chimera run` startup | proactive refusal | exit 2 with recovery hint, BEFORE any provider spend |
| **3 (this PR)** | git `pre-commit` hook | proactive evidence | append structured entry to `mind/CHRONICLE.md`; does NOT block the commit |

### Layer 2 — `chimera run` refusal

Detector reused via shared `detect_main_worktree_branch_drift` helper
extracted from doctor.py — the same logic drives both Layer 1's warn
and Layer 2's refusal, eliminating drift between the two responses.

Override: `CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1` (operator-aware
single-use escape hatch, mirrors the
`SOAK_SKIP_CONCURRENT_CHECK=1` precedent from PR #51). Documented in
the refusal message and in the `chimera run --help` epilog.

The refusal message names the worktree, the branch, the recovery
sequence (4 numbered steps), and the override knob.

### Layer 3 — pre-commit hook (evidence-only)

Pure-bash `pre-commit` hook installed at `.git/hooks/pre-commit` via
`chimera doctor --install-hooks`.

- **Does NOT block the commit.** Blocking legitimate operator commits
  (release commits, hotfixes, recovery sessions) would be hostile.
- Fires when: invoked from the toplevel main worktree AND HEAD ≠ `main`.
- Appends a grep-friendly Markdown block to `mind/CHRONICLE.md` so
  future chips can count occurrences:
  `grep -c "chip-branch-jump detected" mind/CHRONICLE.md`.

Idempotent installer with sentinel marker (`# chimera-pre-commit-hook v1`).
Refuses to clobber a foreign hook — operator must remove the existing
hook or merge our content manually.

## CHRONICLE entry format (locked)

```
## YYYY-MM-DD HH:MM:SS — chip-branch-jump detected at commit time

**Event**: pre-commit hook fired
**Worktree**: <toplevel> (= git toplevel)
**Branch**: <branch>
**Commit author**: <email>
**Mitigation**: this commit landed but the chip-branch-jump is recorded for audit.
**See**: ADR 0114, PR #46 (Layer 1), ADR 0141 (Layers 2+3).
```

## Trade-offs and honest limits

- **Layer 2 false positives**: an operator legitimately working on a
  feature branch from the main worktree (rare; e.g. recovery sessions)
  will hit the refusal. Mitigated by the override env var.
- **Layer 3 false positives**: legitimate operator commits on feature
  branches from the main worktree (release commits, hotfixes) WILL
  generate CHRONICLE entries. Acceptable — the format is grep-distinguishable
  and append-only.
- **Layer 3 hook installation**: requires explicit operator opt-in via
  `chimera doctor --install-hooks`. Auto-installation on `chimera serve`
  startup was considered and rejected — silently modifying `.git/hooks/`
  without consent violates the surface contract.

## Composed-tier outcome (ADR 0114 bookkeeping)

When this PR lands, the chip-branch-jump composite goes from
"1 of 3 shipped" (PR #46) to "3 of 3 shipped" — the composite is
COMPLETE. ADR 0114's composed-tier N counter advances 1 → 2 (v4.116
was the first composed completion; this is the second). ADR 0114
amendment is intentionally deferred to a follow-up chip for scope
discipline.

## References

- [ADR 0114](./0114-autonomous-delivery-contract.md) — composed-tier framework
- [ADR 0120](./0120-soak-runner-watchdog.md) — "ship the detection AND the response together" precedent
- PR #46 — Layer 1 (`chimera doctor` warn)
- PR #51 — `SOAK_SKIP_CONCURRENT_CHECK=1` override precedent
