# ADR 0160 — Internal critic (adjudication for no-contract autonomy)

**Status**: Accepted (2026-05-31). Thrust ③ of the no-contract roadmap — the
judgment faculty the faithfulness gate proved is irreducible.

## Context

The no-contract goal asks Chimera to ship production-worthy code without a human
writing the acceptance test. The faithfulness gate (ADR 0159) covers the
detection half: mutation finds under-tested logic, the differential finds
changed behaviour. But building it surfaced a hard boundary — those tools
**detect** a behaviour problem yet cannot **adjudicate** the correct direction
when the suite is silent. The first live soak's `isdigit` regression is the
canonical case: the differential flags that `to_snake("foo2Bar")` changed, but
only judgment — reading the docstring "lowercase or a digit" — decides the drop
is wrong. A second proof run (faithfulness step in the INBOX) produced a faithful
fix, but that is one data point and a prompt nudge, not adjudication.

What a human reviewer supplies, and gates cannot, is **judgment over the diff in
light of intent**. To approach production-worthy-without-contracts, Chimera needs
that faculty internally.

## Decision

`chimera/core/critic.py::review_change(diff, *, provider, model_id, goal,
docstring, faithfulness)` — give a (cross-model) reviewer the change's goal, the
diff, the touched code's docstring (the intent the tests may not pin), and the
machine-derived faithfulness report, and have it adjudicate: approve ONLY if the
change faithfully fixes the bug without silently removing or regressing untested
behaviour. Returns a structured `CriticVerdict` (`approved`, `concerns`,
`rationale`). Mirrors the charter generator's provider pattern.

**Fail-closed.** A verdict that cannot be parsed, omits an explicit `approved`,
or whose `approved` is not literal `true` is NOT an approval; a provider error is
NOT an approval. An unreadable or absent critic must never wave a change through.
The deterministic gates (verify, mutation, differential) remain authoritative —
the critic adds the judgment they cannot, it does not replace them.

## Consequences

### Pros

- Supplies the missing adjudication leg: a contract-free stand-in for human
  review that can read intent (docstring) + the flagged deltas and decide
  faithful-or-not — the judgment the differential explicitly cannot make.
- Cross-model by construction (the reviewer can be a different model than the
  author), so it is an independent check, not the author grading itself.
- Fail-closed: the safe default is rejection, so a flaky/garbled critic degrades
  to "needs human review," never to a false approval.

### Cons / honest disclosures

- **The critic is itself an LLM judgment** — it can be wrong (approve a subtle
  regression, or reject a good change). It raises the floor; it is not infallible
  and does not make unreviewed merge safe on its own. Trust must be earned
  empirically (track its verdicts against outcomes), exactly as for every other
  capability here.
- This is the GATE primitive (prompt + parse + provider call), not yet wired into
  the real-task loop as an acceptance step, and not yet validated live against
  the strcase regression (the next chip + an operator run).
- It needs the diff + docstring + faithfulness report assembled by the caller;
  wiring that into the loop is follow-up work.

## Test coverage

`tests/test_critic.py` (13): verdict parsing approves only literal `true`;
reject-with-concerns; bare-json (no fence); **fail-closed** on empty /
unparseable / missing-`approved` / non-bool `approved`; the prompt carries diff +
intent + faithfulness + the faithful/silent-regression framing; and the
provider-driven path with a mock (approve, reject, provider-error fail-closed,
garbage fail-closed).

## Next

- Wire `review_change` into the real-task loop as a post-fix acceptance step:
  assemble the diff + docstring + `chimera faithfulness` output, run the critic,
  and require approval (or surface concerns for the agent to address) before the
  commit phase.
- Live validation: does the critic, given the `isdigit`-dropped diff + the
  docstring, REJECT with the right concern? (operator run)
- Calibrate trust: log critic verdicts vs. eventual human judgement.

## References

- [ADR 0159](./0159-faithfulness-gate.md) — the faithfulness gate whose
  detection/adjudication boundary motivates this.
- [ADR 0158](./0158-real-repo-verification-gate.md) — the real-task loop the
  critic will gate.
