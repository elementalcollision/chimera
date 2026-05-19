# Known limitations and deferred work

Living document tracking gaps surfaced from real-traffic runs that
haven't yet been addressed. Each entry should link to its
remediation ADR / version once shipped.

## Open

_None._

---

### L-3 — Compound synthesis tasks fragment and hit `max_rounds`

**Surfaced:** v4.1 through v4.4 cycles, same task each time:
"Combine the original embedded-vs-server graph DB summary with the
newly generated critique into a final conclusion document at
`mind/graph_db_final.md`."

**Observed:** The model fragments the task into many small reads
(`cat`, `head`, `grep`) — 20–24 tool calls per cycle — and runs out
of rounds before performing the final write. `max_rounds=12` is
plenty for a multi-tool task with a single deliverable; the model's
strategy is wrong, not the budget.

**Impact:** No false-positive completion (v4.3 catches it). The
target artifact never lands; the task stays `[ ]` forever.

**Path to fix:** Two non-exclusive options:
1. System-prompt nudge in the voice block: "when a task asks for a
   single deliverable file, prefer one focused read + one focused
   write over many small reads."
2. ACT-level mid-loop hint: when round count exceeds half of
   `max_rounds` and no write to the declared artifact has happened
   yet, inject a system message reminding the model of the target
   path.

Option 1 is cheapest; (2) is more invasive but more reliable. Try
(1) first and remeasure.



---

## Closed

### L-4 — `CHIMERA_ENGINES_ENABLED=0` leaked on planner cycles *(closed in v4.12)*

**Surfaced:** v4.5 live-spin. With the env var set, an Nth-cycle PLAN
phase still fired the Opus planner. Daily-engine path honored the
flag; the planner path didn't.

**Closed in:** v4.12 via [ADR 0034](adr/0034-engines-kill-switch.md).
`_phase_plan` now early-returns when `CHIMERA_ENGINES_ENABLED=0`
gating BOTH the daily engines AND the Opus planner under a single
flag.

---

### L-3 — Compound synthesis tasks fragment and hit `max_rounds` *(closed in v4.5)*

**Surfaced:** v4.1 through v4.4. Same task: combine summary + critique
into one `.md` file. Model fragmented into 20-30+ small reads, never
reached the final write.

**Closed in:** v4.5 via [ADR 0028](adr/0028-adaptive-budgets.md). Two
levers:
1. `dynamic_max_rounds(task_text)` scales per-task budget by declared
   artifacts and named tool keywords (capped at 32).
2. When `(finish_reason="max_rounds", missing_artifacts)` recurs ≥2
   times with overlapping token-signature, ACT auto-emits a
   `skill_proposal` mutation for a focused `synthesize_to_file` skill.
Verified live: cycle 8 budget jumped 12→16, cycle 9 auto-proposed
mutation #1 with the synthesis skill spec. Drift detector also
demoted the plan independently. Pattern → diagnosis → proposal.

---

### L-2 — Shell `cwd` defaulted to `mind/`, so `state/x` landed at `mind/state/x`

**Surfaced:** v4.3 live-spin cycle 6. Agent wrote to `state/x` via a
shell call without setting `cwd`; default cwd was `mind/`, so the
file landed at `mind/state/x`.

**Closed in:** v4.4 via [ADR 0027](adr/0027-shell-default-cwd.md).
Shell default cwd switched to the mind+state common parent (repo
root) and that parent added to allowed_roots when discoverable.
Relative `state/x` and `mind/x` paths now resolve as the model
intends.

---

### L-1 — `completed=True` doesn't verify promised artifacts

**Surfaced:** v4.2 verification cycle. ACT reported
`completed=True` on `stop_reason="stop"` regardless of whether the
promised files (`state/fib_validation.log`,
`mind/graph_db_final.md`) actually landed.

**Closed in:** v4.3 via [ADR 0026](adr/0026-artifact-verification.md).
`expected_artifacts(task_text)` extracts backtick-quoted paths under
`state/` / `mind/`; ACT checks each one exists after `stop` and
downgrades to `finish_reason="artifact_missing"` with the missing
list when any are absent.
