# ADR 0163 — Trust-gated autonomous self-PR

**Status:** Accepted (off by default; opt-in)
**Date:** 2026-06-02
**Builds on:** ADR 0102 (operator-side submit-pr), ADR 0162 (in-loop critic gate),
ADR 0008 (trust ladder)

## Context

ADR 0102 deliberately made PR submission **operator-invoked**: the agent never
holds push credentials, and a human runs `chimera submit-pr` after review. That
was the right call while the loop was unproven. As of 2026-06-02 the no-contract
enforced loop is validated and reproducible (the characterization arc): Chimera
self-selects work, builds it, and lands a commit only through the fail-closed
in-loop critic gate, with the escalator rescuing primary false-rejects.

The next rung of the autonomy ladder is letting Chimera **propose** its own PR —
without weakening the threat model ADR 0102 established.

## Decision

Add `chimera/core/self_pr.py::maybe_self_pr`, a **gated wrapper** over the
existing `submit_pr` machinery. It opens a PR autonomously only when ALL hold:

1. **Opt-in.** `CHIMERA_SELF_PR=1`. Unset (the default) → no-op; behaviour is the
   ADR 0102 manual-handoff status quo. Enabling it in a soak is a deliberate
   operator action.
2. **Trust ≥ T4 (ADAPTIVE).** The agent must have earned broad autonomy on the
   ADR 0008 ladder. (Operator-selected envelope, 2026-06-02: "Balanced — T4 +
   draft".)
3. **Gate-approved commit.** The worktree's last `critic-gate-log.jsonl` decision
   is `allowed: true` (ADR 0162). A self-PR can only ever propose a change the
   safety floor already approved. Fail-closed on missing/unreadable/empty log.
4. **Full `submit_pr.validate()`.** The same secret-path / fix-without-test /
   runtime-pytest re-validation the operator verb runs — no weaker path to a PR.

The PR is opened **as a DRAFT and is never merged.** Nothing lands without a
human marking it ready AND merging. The autonomy granted is "propose," not "ship."

## Threat model — why this doesn't weaken ADR 0102

- **No new credential surface.** `maybe_self_pr` delegates to the same
  `submit_pr` that pushes from the operator's git config; the agent still holds
  no push credentials. The change is *who triggers* the (already-credentialed)
  push, gated on earned trust.
- **Strictly additive / fail-closed.** Every gate defaults to "skip." With the
  env unset, the code path is inert. Any unreadable trust state or gate log →
  skip, not fire.
- **Two human actions still required to merge** (mark-ready + merge), preserving
  the human as the terminal authority.
- **Draft is structural, not advisory** — `draft=True` is asserted by a unit test
  (`test_fires_draft_when_all_gates_pass`).

## Consequences

- Chimera can surface a reviewable PR the moment it earns T4 and produces a
  gate-approved change — closing the last manual step before human review,
  without auto-merging.
- The trust ladder gains teeth: T4 now *unlocks a concrete capability*, which
  makes trust progression worth measuring (a follow-up: validate T0→T4 promotion
  from accumulated gate-approved commits).
- Reversible: unset `CHIMERA_SELF_PR` to return to pure manual handoff.

## Tests

`tests/test_self_pr.py` — each gate exercised via the `submit_fn` seam (no
git/gh): skips on env-unset, trust < T4, missing gate log, last-decision-blocked;
fires (draft) only when all four gates pass.

## Amendment (first LIVE self-PR, 2026-06-02)

The capability fired end-to-end against a real gate-approved worktree
(`chimera-soak/realtask-2026-06-02-1714`, the batch-4 `[agent]` commit `87a979c`
— a clean 3-import ruff cleanup that landed via primary-reject → opus-escalator-
rescue). Two integration gaps surfaced first in a **side-effect-free dry-run**
(branch pattern only matched `chimera-soak/v<N>`; the soak's uncommitted `mind/*`
journal tripped the clean-tree check) and were fixed before any PR opened.

`maybe_self_pr` then fired for real:

```json
{"fired": true, "submit_ok": true, "branch": "chimera-soak/realtask-2026-06-02-1714",
 "pushed": true, "pr_url": "https://github.com/elementalcollision/chimera/pull/254"}
```

**PR #254 opened as a DRAFT** (`isDraft: true`) — title `[agent] fix the 3 ruff
lint finding(s) in tests/test_locomo.py`, audit `submit_pr.success`. Every gate
held: opt-in (`CHIMERA_SELF_PR=1`), trust (T5 ≥ T4 floor), gate-approved commit
(`allowed:true`), full `submit_pr.validate()` — and the human remained the
terminal merge authority. The full no-contract chain ran without a human until
that merge gate: self-scan → build → fail-closed critic gate (escalator rescue) →
earned trust → autonomous draft PR.

Records: `mind/research/landmark-first-autonomous-self-pr-2026-06-02.md`.
