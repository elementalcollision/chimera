# Self-origination design — 2026-05-31

Design research note (NO production code) for **thrust ②** of the no-contract
autonomy roadmap: making Chimera scan its OWN repository for real maintenance
work and **originate its own tasks**, so the existing real-task loop
(`scripts/real_task_soak.sh`, ADR 0158) can run without a human specifying WHAT
to fix.

Read alongside `mind/research/no-contract-autonomy-state-2026-05-31.md` (the
frame). That note's load-bearing finding governs this design: contract-free
verification bottoms out at **detection**; shipping requires **adjudication**,
which is a judgment call, and the critic (ADR 0160) is **assumed-not-earned**
(calibrated on 4 obvious cases, 100% — a smoke test, not a trust metric). The
state note is explicit that ② "must not precede a trustworthy
correctness/adjudication signal, or it will just mass-produce
confident-but-unreviewed changes."

---

## 1. Goal & framing — self-origination is the WHAT leg, and it is PROPOSAL-ONLY

The contract externalises three judgments (state note, §"The frame"):

| Judgment | Status |
|---|---|
| **WHAT** to change | self-charter exists (ADR 0152/0153); **self-origination from the repo is the open ② work** |
| **CORRECT?** | verify · mutation · differential (ADR 0158/0159) — built, partly proven |
| **GOOD ENOUGH?** | internal critic (ADR 0160) — built, **not calibrated** |

Self-origination supplies the WHAT: today a human hand-writes `TASK_GOAL` /
`TASK_FILES` / `TASK_TEST` / `TASK_BASE` for `real_task_soak.sh`
(`scripts/real_task_soak.sh:47-50`). Thrust ② removes that human by deriving the
triple from the repo itself.

**It must be PROPOSAL-ONLY at first.** The deliverable of the first chips is a
*ranked list of candidate task triples a human/operator reviews and picks from* —
NOT an auto-launch of the soak. Three independent reasons, all from the state
note:

1. **The adjudication leg is not trustworthy yet.** The critic is one LLM
   judgment with a 4-case smoke test (ADR 0160 amendment). Auto-originating AND
   auto-running means an uncalibrated critic is the only thing between a
   self-picked task and a self-committed change — exactly the
   "confident-but-unreviewed churn" the state note warns ② would produce.
2. **The loop's own reliability is unproven across shapes.** "One task, one
   shape" (state note §ASSUMED): everything is validated on single-file,
   single-function, string-arg fixes. Origination that picks an off-distribution
   task hits W1-class failure modes (agent over-claims "done" with no-op tool
   calls — ADR 0158 W1 amendment) with no human in the loop to notice.
3. **Origination precision is itself unmeasured.** We have no data on what
   fraction of machine-surfaced candidates are real, valuable work vs noise. A
   human accept/reject step is both the safety rail AND the labelled data that
   later earns auto-origination (§6).

So: **scan → score → emit ranked candidate triples → human picks → existing soak
runs the chosen one unchanged.** The soak's manual-handoff (no auto-push/PR/merge,
ADR 0158) stays. ② changes only WHO writes the triple, not how it is verified or
shipped.

---

## 2. Candidate sources — mechanically-detectable maintenance signals in THIS repo

Each source below is something a deterministic `self_scan` can detect with a
command already available in this repo, plus the rule for converting a hit into a
`(TASK_GOAL, TASK_FILES, TASK_TEST)` triple the soak consumes.

The soak's gate is `uv run chimera verify --ruff <file> [--test <target>]`
(ADR 0158 Chip 3). A candidate is only useful if it produces a triple whose
**convergence is checkable by that gate** — i.e. the work makes a `ruff`/`pytest`
signal flip from red→green, scoped to `TASK_FILES`.

### A. Lint debt (ruff) — the cleanest first source

- **Detect:** `uv run ruff check --output-format json chimera/` (per-file,
  per-rule findings with line numbers). The state note's anchor case is real:
  **`chimera/cli.py` carries 14 pre-existing ruff findings** that an un-narrowed
  `chimera verify` reports as FAIL (ADR 0158 Chip 2 "honest wrinkle"); CI runs
  pytest only so `main` stays green, so this debt is genuine, latent, and safe.
- **Triple:** group findings by file →
  - `TASK_GOAL` = "Fix the N ruff findings in `<file>` (rules: E501, F401, …)"
  - `TASK_FILES` = `<file>` (single file → tightest scope)
  - `TASK_TEST` = the file's existing test target if one exists (e.g.
    `tests/test_cli_*.py`), else omit — the **ruff half of `chimera verify`**
    *is* the convergence criterion (gate goes red→green when findings clear).
- **Convergence is unambiguous and auto-enforceable** (no behaviour judgment):
  ruff red→green with no test regression. This is the ideal first candidate
  class — it needs *no* critic adjudication to be safe (fixing a lint finding
  doesn't change behaviour if tests stay green).
- **Honest wrinkle for the scanner:** ruff is a dev/CI dependency, not installed
  in every worktree venv (`uv run ruff check` / `python -m ruff` both miss in a
  bare `.venv` here). `self_scan` must treat "ruff not runnable" as *no
  candidates from this source*, never as an error or an empty repo — same
  fail-open discipline as `verify_change` (ADR 0158: a missing program is a
  FAILED check, not a raise).

### B. Failing / flaky tests

- **Detect:** `uv run pytest -q --no-header` and parse the failure summary;
  re-run failures `-p no:randomly` or N× to separate hard-fail from flaky.
- **Triple:** for a hard-failing test pinned to one impl file:
  - `TASK_GOAL` = "Make `<test::node>` pass" / "De-flake `<test::node>`"
  - `TASK_FILES` = the impl file under test (resolve via the test's imports /
    CodeGraph `callees`), kept to one file
  - `TASK_TEST` = the failing node id
- This is the soak's *designed* happy path (ADR 0158 precondition: "if the task
  is 'fix a failing test', that test is already red on `TASK_BASE`").
- **Caveat:** a fix that *changes behaviour* to satisfy a previously-red test is
  exactly where the faithfulness/critic stack matters — so behaviour-changing
  test fixes rank BELOW lint debt (§3), and should carry a flag telling the
  reviewer "critic adjudication load-bearing here."

### C. TODO / FIXME / XXX comments

- **Detect:** `grep -rn 'TODO\|FIXME\|XXX' chimera/ --include='*.py'` — **4 hits
  today** (real, small surface). Filter to ones co-located with a single function
  and an existing test.
- **Triple:** `TASK_GOAL` = the TODO text verbatim + file:line; `TASK_FILES` =
  the file; `TASK_TEST` = nearest test. Low precision (many TODOs are notes, not
  work) → these rank low and lean hardest on human picking. Good *only* as a
  proposal source, never auto-run.

### D. Dead code

- **Detect:** CodeGraph is the right tool — a symbol with **zero callers**
  (`codegraph_callers`) and not exported in an `__all__` / not a CLI entrypoint
  is a dead-code candidate. (External `vulture`/`ruff F401` cover unused imports;
  CodeGraph covers unused *defs* grep can't.)
- **Triple:** `TASK_GOAL` = "Remove unused `<symbol>` in `<file>` (0 callers)";
  `TASK_FILES` = `<file>`; `TASK_TEST` = the file's test.
- **Higher risk** (removal = behaviour deletion, the canonical Goodhart failure
  class from ADR 0159 — the `isdigit` drop *was* a deletion). The differential
  (`chimera/core/differential.py`) and critic must gate it. Ranks low; flagged
  "deletion — adjudication required."

### E. Coverage holes

- **Detect:** `uv run pytest --cov=chimera --cov-report=json` → files/functions
  with low/zero line coverage. Cross-reference the mutation gate
  (`chimera/core/faithfulness.py::assess_faithfulness`, ADR 0159): a file with
  **surviving mutants** is a coverage hole with a *named, test-authorable* blind
  spot (e.g. strcase reports `teeth_score 0.73`, 3 survivors).
- **Triple:** `TASK_GOAL` = "Add a test that kills the surviving mutant at
  `<file>:<line>` (pin `<behaviour>`)"; `TASK_FILES` = the **test** file (the
  change is test-only → near-zero behaviour risk); `TASK_TEST` = that test file.
- **Excellent candidate class:** test-only changes are low-risk AND directly
  advance the no-contract goal (agent authoring the verification the gate
  exposed is missing — ADR 0159's whole thesis). Mutation survivors are
  *auto-enforceable* convergence (survivor killed → done), no adjudication.

### F. Type gaps

- **Detect:** the repo does not wire a type checker by default (ADR 0158:
  "type-checking is not wired by default"). If/when `mypy`/`pyright` is adopted,
  per-file error counts convert exactly like ruff (§A). Until then this source
  yields no candidates — note it, don't fake it.

**Ranking of source *classes* by safety (detail in §3):**
`E (mutation/test-only) ≈ A (lint) > B (test fix, behaviour-neutral) > B (test
fix, behaviour-changing) > C (TODO) > D (dead-code deletion)`.

---

## 3. Scoring / ranking — value × inverse-risk × scope-tightness

Rank each candidate by a small, transparent, **deterministic** score (no LLM in
the scorer — keep the first primitive auditable):

```
score = value × inverse_risk × scope_tightness
```

- **value** — does fixing it flip a real signal? Lint finding / failing test /
  surviving mutant = high (a concrete red→green). Bare TODO = low (may be a note).
- **inverse_risk** — does convergence need behaviour adjudication?
  - *auto-enforceable* (ruff red→green, mutant killed, test-only add): **high
    inverse_risk** — the deterministic gate alone certifies it; the
    uncalibrated critic is not load-bearing.
  - *behaviour-changing* (test fix that alters output, dead-code removal): **low
    inverse_risk** — leans on the differential + the un-trusted critic.
- **scope_tightness** — `1 / |TASK_FILES|`, with a hard preference for
  single-file. Multi-file candidates are deprioritised hard (state note: only
  single-file is proven; multi-file is "unexercised").

Net effect: **small, single-file, low-risk, behaviour-neutral tasks float to the
top** — precisely the shape ADR 0158 proved and the shape that needs the
least-trusted faculty (the critic). The first candidate Chimera ever
self-originates should be a single-file ruff fix or a mutation-survivor test,
not a refactor.

Emit the top-K (start K=3, mirroring `MAX_PROPOSED_TASKS_PER_PLAN = 3` in
`chimera/proposals/generate.py`) with score + the risk flag so the human picker
sees *why* each ranked where it did.

---

## 4. Reuse vs new — prefer reuse

**Already in the repo (reuse, do not rebuild):**

- **Detection primitives** — `chimera/core/repo_verify.py::verify_change`
  (ruff+pytest, structured `VerificationReport`, never-raises — ADR 0158);
  `chimera/core/faithfulness.py::assess_faithfulness` + `differential.py`
  (mutation survivors = coverage holes with named blind spots — ADR 0159);
  CodeGraph (`codegraph_callers`/`codegraph_impact`) for dead-code & scope.
- **Proposal plumbing** — `chimera/proposals/`:
  - `generate.py::ProposedTask` (`text`/`rationale`/`tool_hint`) +
    `MAX_PROPOSED_TASKS_PER_PLAN = 3` — the existing capped proposal shape.
  - `dedup.py::dedup` / `fingerprint` / `cluster_key` — kills duplicate
    candidates ("fix F401 in cli.py" surfacing every cycle) for free.
  - `charter_materialize.py` — the originate→build→deliver materialisation
    pattern a later auto-run chip would mirror.
- **The consumer** — `scripts/real_task_soak.sh` unchanged; it already takes the
  triple via env vars (`:47-50`) and writes its own scope note + faithfulness +
  review INBOX steps.

**The PLAN-phase engines (`chimera/engines/`) — what they give vs. what they
DON'T:**

- `DiscoveryEngine` (`discovery.py`) — Haiku **morning distillation** of recent
  api activity into chronicle bullets. Themes/stuck-patterns, *not* repo
  maintenance signals.
- `CuriosityEngine` (`curiosity.py`) — Sonnet **web research** (`web_search` +
  `http_fetch`) into `mind/wiki/`. Outward-facing; no repo scan.
- `ReflectionEngine` (`reflection.py`) — Sonnet **evening reflection** + a typed
  `deriver`. Introspective prose, not actionable file-scoped tasks.

These are **LLM-narrative engines over the chronicle/web**; none scans the source
tree for mechanical maintenance signals or emits a buildable
`(GOAL,FILES,TEST)` triple. So self-origination needs **one new deterministic
primitive** — `self_scan` — that the engines lack, but it should **emit through
the existing `ProposedTask`/`dedup` shape** and (optionally, later) be *invoked*
on the DiscoveryEngine's morning cadence rather than adding a new scheduler slot.

**Verdict:** new = a small deterministic `self_scan` detector+scorer. Reused =
all detection gates, all proposal plumbing, the entire soak. New code surface is
deliberately tiny.

---

## 5. Proposed chip breakdown

### Chip 1 (first, smallest) — `self_scan` deterministic candidate emitter

A pure function + thin module, no LLM, sources A (ruff) and E (mutation
survivors) ONLY — the two auto-enforceable, behaviour-neutral classes.

- **New:** `chimera/core/self_scan.py` — `scan_repo(repo_root, *, sources=...) ->
  list[TaskCandidate]` where `TaskCandidate` carries `(goal, files, test,
  source, score, risk_flag)`; a deterministic `rank()` (§3); reuses
  `verify_change`/`assess_faithfulness` to detect and `dedup` to dedupe. Fail-open
  on missing tools (ruff absent → that source yields `[]`).
- **Files (≤5):** `chimera/core/self_scan.py`, `tests/test_self_scan.py`, an
  `__init__`/export touch, and an ADR (`0161-self-origination-proposal.md`).
- **Acceptance criterion (testable, deterministic):** given a tmp repo with (a) a
  file carrying a known ruff finding and (b) a file with a known surviving
  mutant, `scan_repo` returns BOTH as candidates, each with a well-formed triple
  whose `TASK_FILES` is single-file, ranked lint/test-only above anything
  behaviour-changing; and a repo with no signals returns `[]` (no make-work).
  Mirror ADR 0158's injectable-checks style so unit tests don't need a real
  ruff/pytest.

### Chip 2 — `chimera self-scan` verb (proposal surface)

- **New:** a CLI verb in `chimera/cli.py` that runs `scan_repo` over cwd and
  prints the ranked candidates as a human-readable table + a copy-pasteable
  `TASK_GOAL=… TASK_FILES=… TASK_TEST=… scripts/real_task_soak.sh` line per
  candidate. **Prints only — launches nothing.**
- **Files (≤3):** `cli.py` (parser + `_cmd_self_scan`), `tests/test_cli_self_scan.py`,
  ADR amendment.
- **Acceptance:** verb exits 0 and emits N ranked candidate lines incl. a ready
  soak invocation; exits 0 with "no candidates" on a clean tree. Integration test
  runs it against the real repo and asserts the `chimera/cli.py` ruff debt
  surfaces as a candidate.

### Chip 3 — precision logging (earns auto-origination later)

- Persist each emitted candidate + the operator's accept/reject (and, if run, the
  eventual soak/critic outcome) to a `self_scan_proposals` table/JSONL. This is
  the labelled dataset §6 needs. Still proposal-only.
- **Acceptance:** an emitted candidate that the operator runs and a human accepts
  is recorded as a true-positive; a dismissed one as a false-positive; a
  precision number is computable.

### Follow-ups (NOT first-wave)

- Sources B/C/D behind the risk flag.
- Wire `self_scan` to fire on the DiscoveryEngine morning cadence (surface
  candidates into a `mind/` proposals file, still human-picked).
- ONLY after critic calibration (state note §1) AND a measured origination
  precision: an opt-in auto-run that picks the top candidate and launches the
  soak — gated by the now-trusted critic.

---

## 6. Falsification criteria — is it working, or producing junk?

Self-origination **works** iff:

1. **Precision is high.** Of the top-K candidates emitted, the fraction a human
   operator *accepts as real, worth-doing work* is high (target a measured
   ≥0.7 before considering any auto-run; the number, not a vibe — same discipline
   as critic calibration, ADR 0160). Chip 3 logs exactly this.
2. **No candidate the correctness stack would reject.** A candidate is junk if,
   when run, the **faithfulness/critic stack rejects the resulting change** (e.g.
   a "dead-code removal" that the differential flags as a silent behaviour
   deletion, or a test fix the critic REJECTs). A good scanner's behaviour-neutral
   candidates (lint, test-only) should *never* trip the critic; if they do, the
   triple-derivation is wrong.
3. **Convergence is real.** Each emitted triple, when fed to `real_task_soak.sh`,
   actually flips its gate red→green (ruff clears / mutant killed / test passes).
   A candidate whose gate can't go green is mis-derived.
4. **No churn loop.** Across cycles, `dedup` prevents the same candidate
   reappearing once addressed; a re-surfaced fixed candidate is a falsifier.

**It is producing junk** (kill or narrow it) if: low human-accept precision; any
behaviour-neutral candidate trips the critic; candidates whose gate never goes
green; or duplicate/already-fixed candidates resurface.

---

## 7. Risks

- **Originating make-work / low-value churn — the headline risk** (state note's
  exact warning for ②). A scanner that surfaces every trivial TODO or stylistic
  nit lets the agent generate a stream of confident, low-value commits.
  **Mitigations:** (a) **proposal-only** — a human picks, so no make-work *ships*
  unwatched; (b) **scoring** down-ranks low-value/high-scope/behaviour-changing
  candidates so the top of the list is genuinely worth doing; (c) starting with
  ONLY auto-enforceable, behaviour-neutral sources (ruff, mutation survivors)
  whose value is a concrete red→green, not a taste call; (d) **precision logging
  (Chip 3)** turns "is this churn?" into a measured number that gates expansion.
- **Behaviour-deletion candidates** (dead code, behaviour-changing test fixes) —
  the Goodhart/`isdigit` failure class (ADR 0159). Mitigated by ranking them low,
  flagging them "adjudication required," and keeping them out of the first wave
  until the critic is calibrated.
- **Premature auto-run.** The strongest mitigation is the hard rule that
  auto-origination waits on BOTH critic calibration (state note §1) AND a measured
  origination precision — never shipped on the same chip as the scanner.
- **Scanner fragility / tool absence.** ruff/pytest/coverage may be missing in a
  given env (observed: ruff absent in this worktree's `.venv`). The scanner must
  fail-open per source (no candidates, not an error), inheriting `verify_change`'s
  never-raise charter (ADR 0158).

---

## Bottom line

Self-origination is the WHAT leg, and it must ship **proposal-only** because the
adjudication leg it would feed (the critic) is assumed, not earned. The
first-wave design is deliberately tiny and reuse-heavy: one new deterministic
`self_scan` primitive that detects **ruff debt** and **mutation survivors**
(the two auto-enforceable, behaviour-neutral signals), derives single-file
`(GOAL,FILES,TEST)` triples, ranks them value × inverse-risk × scope-tightness,
and emits the top-3 through the existing `ProposedTask`/`dedup` plumbing for a
human to pick — feeding `real_task_soak.sh` unchanged. Everything riskier
(behaviour-changing fixes, dead-code deletion, auto-run) waits behind a measured
precision number and a calibrated critic.
