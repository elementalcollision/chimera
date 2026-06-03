# Chimera value assessment — keep-or-kill decision memo (2026-06-03)

**Audience:** future-us, deciding whether continued investment is justified.
**Posture:** falsification-honest. The damning facts are stated first; nothing is
spun. A value claim that hides its weakest point is worse than no claim.

---

## 1. The damning fact (stated up front)

On the work Chimera has actually demonstrated — removing 2–3 unused imports per
commit — it is **wildly uneconomical and always will be**. The human alternative
is `ruff check --fix`: free, instant, deterministic. Worse, every Chimera commit
incurs a hidden per-commit tax the soak "spend" line does NOT show: a **sonnet
critic call + an opus escalator call** (the primary false-rejected ~100% of these
clean diffs, ADR 0163, so the opus rescue fired on essentially every commit). So
the true cost per lint-fix commit is *build loop + 1 sonnet + 1 opus* — to do
something a 50ms shell command does for $0.

**If the thesis were "Chimera does cheap maintenance," the answer is KILL.** It is
not that thesis.

## 2. What the lint fixes actually were

The trivial, behaviour-neutral tasks were chosen *deliberately* as a crash-test:
they let the **safety machinery** be falsified under zero real risk. You don't
value a crash-test program by the resale price of the wrecked cars. The output
that matters is not the diffs — it's **what was proven about the loop**.

## 3. What IS proven (the asset) — A + D

Demonstrated live, with evidence, this session:

- **End-to-end no-contract autonomy** in a single launch: self-originate (charter,
  teeth 0.86) OR self-select → build → fail-closed critic gate → gated commit →
  trust-gated draft self-PR. No human until the merge gate.
- **The safety floor held under adversarial pressure.** The calibrated critic's
  **0% false-approve** held across every run (27-case ledger + live). The
  escalator rescued primary false-rejects (sonnet rejected clean diffs; opus
  overruled). When I tried to brute-force past secret-detection with
  `allow_entropy=True`, the **guardrail blocked me** — the right fix each time was
  to make a gate *more accurate*, never to override it.
- **It generalizes within behaviour-neutral work**: from test files to production
  source (`loop.py` full PASS, first direct primary approval) and to **net-new
  code** (`numstat_parser`, self-specified + self-built + gate-approved + merged).
- **Trust is now earned from the gate record** (gate-approval rate feeds
  readiness), so autonomy eligibility is coupled to demonstrated faithfulness.

This is a **rare capability**: safe, unsupervised code authoring with a falsifiable
safety floor. That is the durable asset, plus the reusable architecture
(calibrated critic + escalator + trust ladder) and the falsification-honest method
(~17 chips this session, every one found→falsified→fixed).

## 4. The honest economics — C, and the break-even

Chimera does **not** eliminate human review — it still produces a PR a human
merges. So its economic value is **authoring time saved**, minus token cost,
minus any added review overhead:

```
value_per_PR ≈ (author_time_saved × loaded_rate) − chimera_token_cost − review_overhead
```

- **Lint fix:** `author_time_saved ≈ 0` (ruff --fix). value is strongly **negative**.
- **A real change** (a bug fix that needs understanding + a test; a multi-file
  refactor): `author_time_saved ≈ 15–60 min` of senior time. A few dollars of
  tokens can win — **IF** it converges reliably and the escalator tax is contained.

**Break-even is a task-complexity threshold, not a fixed number.** Chimera pays
only above the complexity where authoring is non-trivial. We have never run it
there — and that is the whole question.

### What is NOT yet proven (the gaps that decide it)
1. **Convergence reliability** — 2/3, not 3/3, even with a pinned model.
2. **Escalator tax** — ~100% of commits triggered opus (primary false-reject);
   ADR 0163's critic-precision work must drive this down or every commit pays the
   opus premium.
3. **Behaviour-CHANGING work, untested.** Every safety result is on
   behaviour-NEUTRAL tasks. The gate's 0% false-approve was measured on the
   calibration set, not on a live attempt to sneak a real behavioural regression
   past it. **This is where the value AND the risk both live, and it is unproven.**

## 5. The decision

The risk question ("can an agent author code unsupervised without a safety
disaster?") is **answered for behaviour-neutral work**. The open question is
purely **economic generalization**: does the proven-safe loop extend to
behaviour-CHANGING work, where authoring time is real enough for the economics to
flip?

**Recommendation: CONDITIONAL CONTINUE — gated on one decisive experiment.**

Run the full stack on a **behaviour-changing task**: a real bug fix where a
failing test *demands* a behavioural change (and a paired adversarial case — a
"gaming" fix that deletes untested behaviour to pass). Falsifiable triggers:

- **KEEP** if: (a) the critic gate correctly **approves the faithful fix AND
  rejects the gaming attempt** on behaviour-changing diffs (safety generalizes),
  AND (b) it converges, AND (c) the escalator tax falls after the critic-precision
  work. Then the capability reaches the task class where the economics can flip,
  and the safety floor is proven where it matters.
- **KILL / PIVOT** if: the gate cannot safely distinguish a faithful behaviour
  change from a regression — i.e., the safety floor is confined to trivia. Then
  Chimera is a beautiful crash-test rig with no road to drive on, and the honest
  move is to harvest the architecture + method as IP and stop the autonomous-loop
  investment.

**The next experiment is the proof.** Not another characterization batch of lint
fixes — those can only re-confirm what we know. A single behaviour-changing trial,
with an adversarial counterpart, settles "worth it" in either direction.

---

### Appendix — what to measure if we continue
- Cost ledger that captures the FULL per-commit cost (build + critic + escalator),
  not just the ACT spend line, so cost-per-faithful-commit is real.
- False-reject rate on behaviour-changing diffs (the escalator-tax driver).
- Convergence rate by task complexity (the reliability axis).
- Author-time-saved estimates per task class (the value axis).
