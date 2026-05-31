# ADR 0161 — Self-origination, proposal-only (thrust ② chip 1)

**Status**: Accepted (2026-05-31). First chip of thrust ② (the "WHAT" leg of
no-contract autonomy). Design: `mind/research/self-origination-design-2026-05-31.md`.

## Context

The real-task loop (ADR 0158) can fix + self-commit a genuine maintenance change,
but a human still hand-writes its `TASK_GOAL` / `TASK_FILES` / `TASK_TEST`. The
"WHAT" leg of no-contract autonomy is letting Chimera derive that triple from the
repo itself — originate its own work.

The no-contract state note is explicit that this must NOT precede a trustworthy
correctness/adjudication signal, or it "will just mass-produce
confident-but-unreviewed changes." The critic (ADR 0160) is calibrated but
modest (0% false-approve / 12 cases). So chip 1 is deliberately conservative.

## Decision

`chimera/core/self_scan.py::scan_repo(repo_root, *, ruff_finder, mutation_finder)`
returns a ranked list of `TaskCandidate`s — `(goal, files, test, source, score,
risk_flag)` — each a ready triple for `real_task_soak.sh`. **PROPOSAL-ONLY: it
launches nothing.** A human picks; the soak (with its manual-handoff and the
full verify/faithfulness/critic stack) runs the chosen one unchanged.

This chip covers ONLY the two **behaviour-neutral, auto-enforceable** sources:

- **ruff debt** (source A): lint findings per file → "fix the lint in <file>"
  (mechanical, behaviour-preserving). `risk_flag=""`.
- **mutation survivors** (source E): a function whose behaviour the suite doesn't
  pin → "add tests that kill the survivors" — a change to the **test** file only,
  so source behaviour is untouched. `risk_flag=""`.

Behaviour-CHANGING sources (failing tests, dead code, TODOs) are deliberately
excluded; they need the risk flag and a trusted critic (follow-ups).

`rank()` orders by `value × inverse-risk × scope-tightness` — test-only above
source-editing, more findings above fewer, single-file above multi. Finders are
**injectable** (unit tests need no real ruff/pytest) and the defaults are
**fail-open**: a missing tool yields no candidates from that source, never a
crash (inheriting `verify_change`'s charter).

## Consequences

### Pros

- The WHAT leg, built at the safe end: every emitted candidate is
  behaviour-neutral and single-file, and the operator (not the agent) decides
  what runs. No new trust is assumed.
- **Live-validated on this repo:** the real ruff finder surfaces 75 candidates,
  ranking `chimera/cli.py` (14 findings — the debt noted all along) #1 with a
  copy-pasteable soak command. Chimera now originates real maintenance work.
- Reuses existing primitives (ruff via the same path as `chimera verify`;
  mutation via `assess_faithfulness`); the new surface is the orchestration +
  ranking + the `TaskCandidate` triple.

### Cons / honest disclosures

- **Proposal-only by design** — no auto-launch. That is the point: the critic is
  not yet trusted for unattended origination + run (state note §1).
- **Volume, not yet precision.** 75 ruff candidates is a lot; ranking floats the
  highest-value to the top but origination *precision* (what a human actually
  accepts) is unmeasured — chip 3 (precision logging) is what earns auto-run.
- Mutation source is opt-in (None by default) because whole-repo mutation is
  expensive; a caller must supply the finder / file-test pairs.
- Two sources only; the behaviour-changing classes are future work behind the
  risk flag.

## Test coverage

`tests/test_self_scan.py` (9): the acceptance criterion (both sources → ranked
single-file triples, mutation's change is test-only, all `risk_flag=""`);
test-only ranks above ruff; a clean repo yields `[]` (no make-work); mutation
opt-in default-skips; zero-count findings dropped; a finder exception fails open;
the soak command is copy-pasteable; ranking is deterministic/stable; and an
**integration** test running the real ruff finder surfaces `chimera/cli.py`.

## Amendment (chip 2 — the proposal verb, 2026-05-31)

`chimera self-scan [--base REF] [--limit N]` is the human-facing proposal
surface: it runs `scan_repo` over the cwd and prints the ranked candidates, each
with its score, source, risk flag, goal, and a **copy-pasteable
`real_task_soak.sh` invocation**. **It prints only — it launches nothing**; the
output ends with an explicit "pick one and run it yourself" banner, and the
handler has no code path that starts a soak. Exit 0 whether or not candidates are
found (a proposal surface, not a gate). Live on this repo it lists
`chimera/cli.py` (14 findings) as candidate #1 with a ready command.
`tests/test_cli_self_scan.py` (5): empty → the no-candidates note; ranked output
with N soak lines + the proposal-only banner; `--limit` caps; `--base` flows into
the command; and a real-repo integration run.

## Amendment (chip 3 — precision logging, 2026-05-31)

`chimera/core/self_scan_log.py` is the labelled-data layer: an append-only JSONL
of `proposal` and `decision` events keyed by a deterministic content-hash
`proposal_id` (re-emitting a candidate is idempotent). `precision_report` folds
it — latest decision per proposal wins — into `proposed / accepted / rejected /
undecided` and **origination precision** = accepted / (accepted + rejected). The
`self-scan` verb gains `--log` (persist + print ids), `--accept ID` / `--reject
ID` (record the operator's call), and `--precision` (print the report). Charter:
never raise on a malformed line; timestamps injected for determinism.

This is the metric that, together with critic calibration, eventually earns an
opt-in auto-run — until both are healthy the loop stays proposal-only and the
human supplies the labels. `tests/test_self_scan_log.py` (8) pin the log math
(deterministic id, round-trip, mixed-decision precision, latest-decision-wins,
idempotency, malformed-line skip); `tests/test_cli_self_scan_log.py` (4) pin the
verb wiring (log writes + ids, accept/reject → precision, empty report, no write
without --log).

## Next

- Behaviour-changing sources behind the risk flag; DiscoveryEngine cadence.
- ONLY after a healthy origination precision AND critic calibration: an opt-in
  auto-run that picks the top candidate and launches the soak.

## References

- `mind/research/self-origination-design-2026-05-31.md` — the design.
- [ADR 0158](./0158-real-repo-verification-gate.md) — the loop the triples feed.
- [ADR 0160](./0160-internal-critic.md) — the adjudicator that must be trusted
  before auto-origination.
