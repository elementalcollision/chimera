# Witness over-rejection — diagnosis + asymmetric-voting fix

**Date**: 2026-05-30
**Surfaced by**: every R3 build soak (v42, v43-strcase, v44) logged
`witness_rejected` on CORRECT diffs (tests green), churning the loop.

## Root cause

The cross-provider witness panel (`chimera/core/witness_panel.py`) decided
APPROVE/REJECT via `panel_decision`, whose rule defaulted to **`unanimous`**
(`voting_rule()`): with a 3-model panel, **any single dissent rejected**. The
rationale (v4.103): "foundational-code blast radius makes false-negative cost ≫
false-positive cost."

The build soaks disproved the second half empirically. On a CORRECT build diff,
one model raising an idiosyncratic code-quality concern (a nitpick, a
hallucinated "possible off-by-one", a convention quibble) rejected the whole
diff → `witness_rejected` → the agent re-worked correct code → churn + cost, on
every build soak. The false-POSITIVE cost is real and recurring; the unanimous
default optimized only against false negatives.

## The fix — asymmetric voting

Not a flat switch to majority (that would weaken the catch unanimity was
actually chosen for — the v13 `RAW_ALLOWLIST` write-capability expansion, a
single-model security flag). Instead, `panel_decision` is now **asymmetric**:

1. **Charter override (rule-independent).** If ANY disapproving witness raises
   a **charter / security / scope** concern (`_is_charter_concern` — matches
   charter, read-only, allow-list, MUST NOT, sandbox, RAW_ALLOWLIST, out-of-
   scope, privilege, "crosses", …), the panel REJECTS regardless of count. A
   single model spotting a threshold crossing stays decisive — the high-value
   catch is fully preserved.
2. **Majority for the rest (new default).** Ordinary code-quality concerns now
   require MORE than half the panel to disapprove. A lone nitpick on a correct
   diff no longer rejects.

`CHIMERA_WITNESS_VOTING=unanimous` restores the strict rule for a high-stakes
run; `_is_charter_concern` deliberately errs broad (matching = strict), so the
relaxation only ever loosens the genuinely-low-stakes code-quality class.

## Why this is the right shape

- The catch the gate exists for — un-test-covered security/scope crossings
  (v9/v10/v13/v14) — is untouched: those flag on any single dissent via the
  charter override.
- The churn the gate caused — single-model nitpicks on test-green build diffs —
  is removed: those need a majority now.
- Test-covered build bugs are caught by the PRIMARY test gate anyway, so the
  marginal value of a single-model-only witness catch there was low while its
  false-positive cost was high.

## Tests

`tests/test_witness_panel.py`: default-is-majority; single code-quality dissent
approves under majority (the fix); charter dissent rejects under majority (catch
preserved); two code-quality dissents still reject (genuine signal); charter
override applies in both modes; `_is_charter_concern` detection. Full suite:
1767 passed, 5 skipped.

## Next

Confirm in-loop on the next R3 build soak: `witness_rejected` should drop to
near-zero on correct diffs, while a deliberately scope-crossing diff still trips
it. (The richer soak ledger from the artifact-detail chip + this change make
the next build soak the cleanest yet.)
