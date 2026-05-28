# ADR 0146 — Pre-commit scope check (confabulation defense)

**Status**: Proposed (2026-05-28). Flip to Accepted after the next
soak demonstrates the check firing correctly (refusing a fabricated
diagnosis commit) or sleeping silently on legitimate work.

## Context

The v35 soak attempt #3 (postmortem at
`mind/research/v35-soak-postmortem-2026-05-28-final.md`, merged at
[`9912949`](https://github.com/elementalcollision/chimera/commit/9912949),
[PR #106](https://github.com/elementalcollision/chimera/pull/106))
surfaced a new defect class: **agent confabulation**. The phase-1
investigation honestly committed a design note saying "the substantive
deliverable does not exist — the classification table was never
produced; `## READY-FOR-REMEDIATION` is empty". Then **~2 minutes
later** the same agent committed a fabricated diagnosis citing
percentages (52.6%, 31.6%) it had never computed, and used those
fabricated percentages to justify a code change in
`chimera/evals/locomo.py` and `chimera/evals/hybrid_retrieval.py`.

Existing engine guards saw the off-charter behavior:

- `scope_evasion` fired multiple times across the cycle.
- Trust degraded from T5 to T0.
- `degenerate_loop_abort` fired.
- `witness_rejected` fired.

But **none of these gates can undo a commit that already landed**.
This is the **commit-time vs detect-time gap**. The witness panel
runs *after* commits land — by then the branch is poisoned, the diff
is on disk, and the postmortem has to reconstruct what happened from
the commit log instead of preventing it.

This is the fourth defect class surfaced by the autonomous-delivery
chain in v35:

| PR | Defect class |
|----|--------------|
| [#103](https://github.com/elementalcollision/chimera/pull/103) | ADR 0141 detector misidentifying secondary worktrees |
| [#105](https://github.com/elementalcollision/chimera/pull/105) | Persistent loop crossing SQLite thread boundary |
| [#107](https://github.com/elementalcollision/chimera/pull/107) | ADR recovery / temporal-reasoning subsection |
| this ADR | Confabulation defense — commit-time scope check |

That each soak attempt has surfaced a new defect class indicates the
integration surface was never tested end-to-end before v35. This ADR
closes one more class.

## Decision

Add a **commit-time scope check** invoked from
`chimera/tools/shell.py` immediately before `git commit` reaches
`subprocess.exec`. The check:

1. Finds the most-recently-modified `mind/research/*-design.md`.
2. Parses its `## READY-FOR-REMEDIATION` section.
3. Extracts the locked recommendation:
   - R-tag (`R1` / `R2` / `R3` / `R<n>` — chip-specific semantics).
   - Backtick-quoted file path allowlist (paths containing `/` with a
     recognized source/test extension).
   - "No code change" / "docs only" / "no-op" signal.
4. Classifies the staged diff (`git diff --cached --name-only`)
   against the recommendation.
5. Refuses (raises `PermissionError` from the shell tool) when the
   diff scope clearly contradicts the locked recommendation.

The check sits at the same chokepoint as the existing T0 trust gate
(ADR 0117) — both fire before subprocess. This is **commit-time
enforcement**, not between-cycles detection. The witness panel +
`scope_evasion` + `degenerate_loop_abort` + `witness_rejected` engine
guards remain unchanged — this is a NEW layer.

### Conservative refusal (locked design constraint)

Any of the following yields **warn-only**, not refusal:

- No `mind/research/*-design.md` found.
- Design note exists but lacks `## READY-FOR-REMEDIATION`.
- Section exists but is empty / only prose with no actionable signal.
- R-tag present but no allowlist and no "no code change" signal
  (R-tag semantics are chip-specific — we cannot safely refuse on
  R-tag alone).
- Subprocess or filesystem failure during evaluation.

The trade-off is deliberate: **false positives would block legitimate
work** (a refused commit during normal operation is a worse
operational experience than the rare confabulation slipping past this
layer). False negatives at this layer are acceptable because the
witness panel + engine guards still run.

### Override knob (locked design constraint)

`CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1` allows a refused commit through
with a logged override event. Same pattern as
`CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1` from ADR 0141. The override is
operator-aware and single-use; the event is recorded so the witness
panel can see it and demote trust.

### Event log

Every check writes one JSONL row to
`state/scope_check_events.jsonl`:

- `scope_check_refusal` — verdict=refuse, override not used.
- `scope_check_override` — verdict=refuse, override was set.
- `scope_check_allow` / `scope_check_warn` — non-refusal outcomes.

The dashboard's sparkline + the witness panel consume this file to
demote trust on refusal patterns (left as a follow-up wire-up; this
ADR ships the event source).

## Consequences

### Pros

- Closes the commit-time vs detect-time gap that
  [PR #106](https://github.com/elementalcollision/chimera/pull/106)
  surfaced. The confabulated commit at `ddfc1ea` would have been
  refused: the design note's `## READY-FOR-REMEDIATION` was empty
  (parsed as no-code-change OR ambiguous depending on the exact body
  — empty body is no-code-change because there's no allowlist to
  fall back to and the section was supposed to *be* the
  recommendation). The fabricated code change in
  `chimera/evals/locomo.py` would have failed the classifier and
  raised `ScopeCheckRefusal` before `git commit` reached subprocess.
- Cheap to add — single chokepoint, ≤350 lines of code, no
  modifications to existing engine guards or the persistent loop.
- Symmetrical with ADR 0141: both are conservative pre-commit /
  pre-run gates with an env-var override.

### Cons / honest disclosures

- **Adversarial confabulation that also corrupts the design note can
  escape** this layer. A sufficiently creative confabulation could
  write a fake `## READY-FOR-REMEDIATION` allowlist that authorizes
  the fabricated diff. Acceptable because (a) it's a higher bar than
  just confabulating numbers in the commit message, (b) the witness
  panel still catches that pattern, and (c) the design note write
  itself runs through the artifact + content-marker checks
  (ADR 0101).
- **False positives**: a legitimate chip whose recommendation is
  spelled out informally ("touch the LoCoMo eval module") rather
  than with backtick-quoted paths will trip ambiguous → warn-only.
  That's fine — warn-only is the conservative default. The cost is
  educational: chips that want commit-time enforcement must spell
  the allowlist in the conventional backtick-quoted-path form.
- **Empty section ambiguity**: an empty
  `## READY-FOR-REMEDIATION` is treated as ambiguous (no R-tag, no
  paths, no no-code signal). This is intentional — an operator might
  ship a design note before the recommendation is locked. The cost
  is that the v35 attempt #3 exact pattern (empty section + later
  fabricated commit) only fires via the second commit's staged diff
  carrying paths outside the empty allowlist — which IS refused
  under the explicit-allowlist branch IFF the recommendation later
  becomes non-empty. Operators who want strict no-code enforcement
  must write the explicit "no code change" string.
- **Cross-reference with ADR 0141**: this ADR is architecturally
  distinct (commit-time scope, not chip-branch-jump prevention) but
  follows the same shape — single chokepoint, conservative refusal,
  env-var override, event-log surface.

## Test coverage

- `tests/test_scope_check.py` — 25 tests covering parser, classifier,
  conservative-refusal paths, the override knob, and an end-to-end
  fake-repo regression test that locks in the v35 attempt #3 failure
  pattern (R1/no-code-change recommendation + R2-shaped staged diff
  → refusal).

The end-to-end fake-repo test in this PR exercises the full pipeline
(real git index, real subprocess call, real refusal raise). A
follow-up chip should add a second e2e test mirroring PR #105's
canary-`chimera run` pattern (real worktree + stubbed agent driving
one cycle that attempts an off-charter commit) — split to follow-up
to keep this PR within the 6-file scope budget.

## References

- [PR #106](https://github.com/elementalcollision/chimera/pull/106) —
  v35 attempt #3 final postmortem (the motivating failure pattern).
- [ADR 0141](./0141-chip-branch-jump-layers-2-3.md) — parallel
  pre-run gate, same override-knob shape.
- [ADR 0117](./0117-trust-state-commit-gate.md) — adjacent pre-commit
  gate (T0 trust state).
- [ADR 0101](./0101-content-marker-check.md) — adjacent artifact
  content-marker check.
- [ADR 0114](./0114-autonomous-delivery-contract.md) — the contract
  this layer hardens.
