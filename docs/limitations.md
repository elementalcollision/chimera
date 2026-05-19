# Known limitations and deferred work

Living document tracking gaps surfaced from real-traffic runs that
haven't yet been addressed. Each entry should link to its
remediation ADR / version once shipped.

## Open

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
