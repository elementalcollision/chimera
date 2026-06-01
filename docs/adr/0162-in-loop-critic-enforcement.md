# ADR 0162 — In-loop critic enforcement (advisory → gate)

**Status**: Proposed (2026-06-01). Design only — implementation is a follow-up
chip requiring explicit operator authorization. The promotion of the internal
critic (ADR 0160) from an advisory step the agent is *asked* to run into a
commit-time *gate* that blocks an unfaithful change before it lands.

## Context

ADR 0160 built the internal critic and wired it into the real-task loop as an
**advisory** step: the phase-2 INBOX asks the agent to run `chimera review`,
address concerns, and re-run until it approves — but nothing *enforces* the
verdict. The agent can ignore it; the commit lands regardless; the verdict ships
with the branch for the human reviewer. That is the safe place to start, but it
is not autonomy: a contract-free loop that cannot stop itself from committing a
silent regression still depends on the human at the end.

Two things now make enforcement designable:

1. **The trust number is measured and holds.** Across four calibration runs
   growing 4 → 27 cases — adding gaming-by-special-casing, a stateful
   dimension, and (this session) **four differential-blind pure-judgment
   near-misses** plus a scenario-blind stateful near-miss — the critic's
   **false-approve rate is 0** (0/12 reject cases in the 27-case run). It has
   never waved an unfaithful change through, including on the hardest probes we
   could construct (regressions whose wrongness the differential cannot see, so
   the critic had only the diff + docstring). A gate that *blocks unless
   approved* is only safe to build because the "approve" side is empirically
   clean.

2. **The cost of enforcement is also measured.** The same run has a 20%
   false-reject rate (3/15), and — the key new finding — one of those is
   `last_seg-correct`, a *clean fix* (not a suspicious simplification) that the
   critic rejected because the differential gave it nothing to corroborate. So a
   naive hard-stop gate ("reject → no commit, ever") would, ~1-in-5 times, block
   a correct change and strand the loop. Enforcement must absorb that cost, not
   inherit it.

## Decision

Promote the critic to a **commit-time gate at the existing chokepoint**, with a
reject path designed around the measured false-reject cost.

### Where it enforces

The same `git commit` interception in `chimera/tools/shell.py` where the
engines-off block, the `CHIMERA_SOAK_FORCE_STALL` lever, the T0 trust gate, the
H1 index-bypass refusal, and the ADR 0146 pre-commit scope check already fire as
`PermissionError` before `subprocess.exec`. The critic gate is added as the
**last** commit gate, after scope check passes:

```
git commit  →  engines-off?  →  force-stall?  →  T0 trust?  →  index-bypass (H1)?
            →  scope check (ADR 0146)  →  CRITIC GATE (ADR 0162)  →  exec
```

It runs last because it is the most expensive (an LLM call) and the most
subjective; the deterministic gates stay authoritative and cheap-first. The gate
is factored into a reusable `chimera/core/critic_gate.py::check_commit_critic(
repo_root, *, goal)` so **both** commit paths are covered: the agent's
`git_commit` tool (via `shell_handler`) and the harness autocommit fallback
(`soak_autocommit.autocommit_if_ready`, ADR 0148). Neither can land a commit the
critic blocks.

### What it checks (verdict bound to the staged diff)

The gate needs the diff + docstrings + faithfulness report the critic consumes.
To avoid recomputing a mutation run and an LLM call on *every* commit, and to
stop the agent from forging a verdict:

- `chimera review` writes a **verdict artifact**
  (`state/critic-verdict-<hash>.json`) keyed by the SHA-256 of the *staged diff*
  (`git diff --cached`), containing the structured `CriticVerdict` plus the
  inputs (goal, docstrings, faithfulness summary).
- The gate computes the current staged-diff hash and accepts a verdict **only**
  if a matching-hash artifact exists and is APPROVED. The verdict comes from the
  trusted `chimera review` code path, not the agent's free text — the agent can
  *run* the reviewer but cannot fabricate its output, and a hash mismatch (diff
  changed since review) invalidates a stale verdict.
- **Fallback (authoritative):** if no valid artifact matches, the gate invokes
  `review_change` itself, synchronously, on the staged diff — slower, but the
  commit is never allowed on an unreviewed diff.

### The reject path (absorbs the false-reject cost)

A REJECT does not hard-stop. It is **reject-requires-confirmation by an
independent model**:

- On the first critic REJECT, the gate escalates to **one independent
  second-opinion** reviewer — a *different* model/tier (reusing the cross-model
  witness pattern already in the codebase). The commit is blocked **only if the
  second reviewer also rejects**.
- Rationale tied to the data: single-critic false-approve is 0 and false-reject
  is 20%. "Approve is taken at face value; reject must be confirmed" rescues a
  lone over-cautious false-reject (critic-2 overrules it) while barely moving the
  false-approve side — a real regression is blocked iff *both* reject, and a
  change that slips would need *two* independent ~0%-false-approve models to both
  err. The compound false-approve stays ≈ 0; the false-reject rate falls.
- When the gate blocks, it raises `PermissionError` with the **concerns
  verbatim** (exactly like the scope-check refusal), so the agent learns *why*
  and can revise + re-commit within the phase budget. A genuine regression is
  the agent's to fix; the concern names it.

### Fail-closed, and the operator escape valve

- **Fail-closed**: an unparseable/empty/`approved`-missing verdict, or a provider
  error, is NOT an approval — it degrades to reject → escalate → and if the
  escalation is also unavailable, the commit is **blocked with a "needs human
  review" handoff**, never silently approved. An absent critic never waves a
  change through. (Same invariant as ADR 0160's gate primitive.)
- **Operator override**: `CHIMERA_ALLOW_CRITIC_REJECT=1` (single-use,
  operator-aware — the same pattern as `CHIMERA_ALLOW_OFF_CHARTER_COMMIT`) lets a
  human ship a change the gate blocked: the manual escape for a *confirmed*
  false-reject (e.g. the `last_seg-correct` shape — a correct fix the differential
  can't corroborate). Every override is logged.

### Calibration-gated activation

Enforcement is **OFF by default**, enabled per-run by `CHIMERA_CRITIC_ENFORCE=1`.
The standing precondition to enable it: the calibration **false-approve rate must
be 0 on the current set**. If any future calibration run shows a false-approve,
enforcement must not be enabled until understood and fixed (falsification
honesty — the gate's legitimacy is tied to the measured number, not to a date).
`chimera doctor` (or the runner preflight) refuses to set the flag if the latest
recorded calibration shows false-approve > 0.

### Trust-ledger integration (the live calibration)

Every enforcement decision — approve / reject / escalation outcome / operator
override — is appended to the soak ledger with the staged-diff hash and the
verdict. This accumulates exactly the in-loop verdict-vs-eventual-human-judgment
record ADR 0160 asked for: the live loop becomes a continuous calibration, and a
real in-loop false-approve (a blocked-should-have-been change that a human later
flags) becomes a recorded, reviewable event rather than a silent miss.

## Consequences

### Pros

- Closes the last human-dependency in the no-contract commit path: the loop can
  now *refuse its own* unfaithful commit, not just annotate it.
- Built on a measured 0% false-approve across 27 diverse cases (incl. four
  differential-blind near-misses and stateful) — the gate blocks on the side the
  evidence says is clean.
- The reject path is designed from the false-reject data, not hope:
  reject-requires-confirmation cuts the 20% false-reject cost; the override valve
  covers the residual; fail-closed keeps the dangerous direction safe.
- Enforces at the real chokepoint, so it covers both the agent's `git_commit`
  and the harness autocommit — no path around it.

### Cons / honest disclosures

- **More LLM calls in the commit path.** Worst case (no cached verdict + a reject
  that escalates) is two reviewer calls per commit attempt. The verdict-artifact
  binding makes the common path one cached lookup; the cost lands only on
  uncached or rejected commits.
- **The critic is still an LLM** (ADR 0160's standing caveat). 0% false-approve is
  a measured rate on a finite set, not a proof. Enforcement raises the stakes of a
  future false-approve from "advisory miss" to "auto-committed regression" — which
  is exactly why activation is calibration-gated and every decision is ledgered.
- **A determined agent could stop running `chimera review`** to avoid producing a
  verdict artifact — but the gate's authoritative fallback (run `review_change`
  itself on an unreviewed staged diff) removes that incentive; skipping review
  just makes the commit slower, not unguarded.
- The independent second-opinion reviewer needs a genuinely different model than
  the author *and* than critic-1 to be a real check; with a single provider
  available it degrades to a different tier, a weaker form of independence
  (disclose in the run record).

## Implementation sketch (follow-up chip — NOT in this ADR)

1. `chimera/core/critic_gate.py`: `check_commit_critic(repo_root, *, goal)` —
   staged-diff hash, verdict-artifact lookup, authoritative fallback, escalation,
   `PermissionError`-on-block with concerns; honour `CHIMERA_CRITIC_ENFORCE`,
   `CHIMERA_ALLOW_CRITIC_REJECT`.
2. `chimera review`: write the hash-keyed verdict artifact.
3. `shell.py`: call the gate after the scope check, behind the enforce flag.
4. `soak_autocommit.py`: call the same gate before the fallback commit.
5. Ledger: record each decision; `chimera doctor` preflight refuses enforce if
   the latest calibration false-approve > 0.
6. Tests: gate blocks on a known regression; lets a known clean fix through;
   reject→escalate→approve rescues a false-reject; fail-closed on provider error;
   override knob; verdict-hash mismatch invalidation.
7. **Live validation (operator run):** enforce ON against the `isdigit`-dropped
   regression — the commit must be *blocked*, not merely annotated — and against
   a clean fix — which must pass. The falsifiable claim is "enforcement stops the
   canonical silent regression from landing autonomously."

## Amendment (implementation — gate primitive + self-commit path, 2026-06-01)

**Status → Accepted** for the implemented surface; two items deferred (below).

Landed:

- **`chimera/core/critic_gate.py`** — `check_commit_critic(repo_root, *, goal,
  reviewer=None, escalator=None)` with the full decision logic: enforce switch
  (off by default), operator override short-circuit, staged-diff hashing,
  hash-bound verdict-artifact load (`load_verdict_artifact` —
  absent/mismatch/corrupt → recompute), authoritative recompute fallback
  (diff + docstrings, no faithfulness report — which the calibration showed the
  critic does not need), and **reject-requires-confirmation** via an independent
  escalator. `reviewer`/`escalator` are injectable (sync tests use mocks; the
  defaults build real cross-model reviewers — sonnet for the primary, opus for
  the independent second opinion). Fail-closed throughout: no provider / unparsed
  verdict / no escalation → block with "needs human review", never a silent pass.
- **`chimera review`** writes the hash-keyed verdict artifact (item 2), bound to
  `git diff --cached` so the gate can accept it without recomputing; a no-op when
  nothing is staged (so `git add` before `chimera review` to hit the fast path).
- **`shell.py`** calls the gate as the LAST commit gate, after the ADR 0146 scope
  check, behind `CHIMERA_CRITIC_ENFORCE` (item 3) — covering the agent's
  `git_commit` tool (genuine self-commit) path.
- **Tests** (item 6): `tests/test_critic_gate.py` (13) — every decision branch
  with injected reviewers + the artifact roundtrip/mismatch/corruption + a
  real-index `staged_diff`; `tests/test_git_commit_tool.py` (+3) — the gate
  through the real commit path: fail-closed **block**, operator-override
  **allow**, and **inert when not enforced** (proves off-by-default). Full suite
  green (2033 passed).

**Deferred to a follow-up chip (honest scope):**

- **Item 4 — `soak_autocommit.py` gating.** The ADR 0148 autocommit fallback is
  NOT yet gated. This is acceptable for the genuine-self-commit enforcement
  scenario (those soaks run `CHIMERA_SOAK_AUTOCOMMIT=0`, so there is no autocommit
  path), but enforce-ON + autocommit-ON is currently a hole. Must close before
  enforce is used with autocommit.
- **Item 5 — ledger record + `chimera doctor` preflight.** Decisions are not yet
  persisted to the soak ledger, and `doctor` does not yet refuse enforce when the
  latest calibration false-approve > 0. The calibration-gated-activation
  invariant is documented but not yet mechanically enforced.
- **Item 7 — the live operator validation run** (enforce ON vs the `isdigit`
  regression) remains the falsification step, pending operator authorization.

## References

- [ADR 0160](./0160-internal-critic.md) — the internal critic + the calibration
  ledger (now 27 cases, 0% false-approve) this enforcement is gated on.
- [ADR 0159](./0159-faithfulness-gate.md) — the deterministic gates the critic
  adjudicates on top of.
- [ADR 0146](./0146-pre-commit-scope-check.md) — the commit-time chokepoint this
  gate joins.
- [ADR 0148](./0148-harness-executed-commit.md) — the autocommit fallback the
  gate must also cover.
