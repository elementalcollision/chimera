# State of no-contract autonomy — 2026-05-31

A consolidation record: what is built, what is *proven*, what is still assumed,
and what is needed before Chimera can ship production-worthy code without a human
writing the acceptance test ("without contracts"). Written after the B1 arc and
the faithfulness/critic thrust. Source of truth is the chip/PR flow; this is the
honest synthesis.

## The frame

A contract (a pre-written acceptance test) externalises three judgments the agent
must internalise to drop it:

| Judgment | Faculty built | Mechanism |
|---|---|---|
| **WHAT** to change | self-charter + teeth (ADR 0152/0153) | originate a spec, prove the test discriminates |
| **CORRECT?** — is it right? | verify · mutation · differential (ADR 0158/0159) | run the real pipeline; detect under-tested logic; detect deleted behaviour |
| **GOOD ENOUGH?** — should it ship? | internal critic (ADR 0160) | cross-model adjudication of faithfulness |
| (reliability spine) | W1/W2/W3 (ADR 0158) | build-completion gate · scope note · telemetry+budget |

## What is PROVEN (live, with the fallback off)

- **Genuine autonomous fix + self-commit.** Chimera fixed a real failing test in
  `chimera/strcase.py` and self-committed it (`[agent]`, author=Chimera-Agent,
  via `git_commit`, `CHIMERA_SOAK_AUTOCOMMIT=0` — no harness crutch). The W1 gate
  fired 22× to stop a hollow over-claim until the fix was actually green.
- **The gate-optimisation failure is real.** In an earlier run the agent made the
  tests pass by DROPPING `or s[i-1].isdigit()` — a silent regression the green
  gate accepted. This is the canonical Goodhart failure for test-gated autonomy.
- **The faithfulness stack catches it — in both directions.** mutation finds
  under-tested logic (on strcase: teeth 0.73, the index branches unpinned);
  the differential reproduces the exact deletion (`foo2Bar → foo2_bar/foo2bar`).
- **The critic adjudicates it (live).** Given the gate-PASSING silent regression
  diff + the docstring + the differential report, `claude-sonnet-4-6` REJECTED
  with the correct concern: *"drops the digit case entirely, so 'foo2Bar' →
  'foo2_bar' becomes 'foo2bar' — a silent regression vs the stated spec."* The
  gate said PASS; the critic said REJECT; the critic was right.
- **With the faithfulness step in the INBOX, a re-run produced a FAITHFUL fix**
  (kept the `isdigit` clause). One favourable data point.

## What is ASSUMED (built, not yet earned)

- **The critic is reliable.** It is one LLM judgment; it adjudicated the canonical
  case correctly ONCE. We have no distribution of verdicts vs. ground truth.
- **The agent acts on the faithfulness/critic signals.** Wiring puts the commands
  in the INBOX; we have not shown the agent reliably runs them and revises on a
  REJECT under the loop's own steam (the in-loop review is advisory/fail-closed,
  not yet a hard ACT gate).
- **The differential is sufficient.** It needs an input corpus (default covers
  single-string functions); arbitrary signatures are uncovered. Deletion outside
  the corpus's reach can still pass.
- **One task, one shape.** Everything is validated on a single-file, single-
  function, string-arg maintenance fix with a focused test. Multi-file, stateful,
  or API changes are unexercised.

## The load-bearing finding

**Contract-free verification bottoms out at DETECTION; shipping without contracts
requires ADJUDICATION, and adjudication is irreducibly a judgment call.** The
mutation gate is auto-enforceable. The differential can *detect* a behaviour
change but cannot decide its correctness when the suite is silent. Only judgment
— the critic (or a human) reading intent — closes that gap. So the path to "no
contracts" is not *more deterministic gates*; it is *trustworthy internalised
judgment*. The critic is that faculty; the open work is earning trust in it.

## What is needed before "merge unreviewed" is defensible

1. **Calibration.** Run the critic across many changes (faithful and not); log
   verdict vs. eventual human judgement; measure false-approve / false-reject.
   Trust is earned by this distribution, not by one good case.
2. **In-loop enforcement.** Promote the review from advisory INBOX step to a hard
   phase-2 acceptance gate (no commit without APPROVE, or escalate), once
   calibration justifies it.
3. **Corpus generality.** Type-/property-driven input generation so the
   differential covers non-string signatures.
4. **Breadth.** Exercise multi-file and stateful changes; expect new failure
   modes and close them the same falsifiable way.
5. **Self-origination (②).** The "living" loop — Chimera scanning its own repo
   for real maintenance work and running the loop unprompted — builds ON this
   stack; it must not precede a trustworthy correctness/adjudication signal, or
   it will just mass-produce confident-but-unreviewed changes.

## Honest bottom line

The machinery for no-contract autonomy now exists end to end, and its single
hardest failure mode (gate-gaming by deletion) is both reproduced and caught by
the new stack — including a live critic rejection on the canonical case. It is
**not** yet trustworthy enough to ship unreviewed: that requires evidence
(calibration, breadth), not more code. The next session's highest-leverage work
is calibration + in-loop enforcement, then ② self-origination on top.
