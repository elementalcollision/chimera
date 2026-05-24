# ADR 0112 — Task-text charter extraction (v4.112)

**Status:** Accepted (2026-05-22) — amends ADR 0110 (v4.110)

## Context

ADR 0110 (v4.110) introduced charter anchoring for the cross-provider
witness panel, motivated by soak v13's RAW_ALLOWLIST over-expansion.
Soak v14 (2026-05-22) was the first end-to-end calibration test of
v4.110 in production. It surfaced a real gap.

The v14 phase-2 INBOX (`scripts/archive/long_cycle_soak_v14.sh:348-415`) put
an explicit charter in front of the agent and the panel:

```
CHARTER for phase 2 (the witness panel will be testing against
these explicitly):
  1. SCOPE: only `--json` on `list` and `summary`. NOT on `clear`.
  2. The `clear` subcommand MUST NOT grow a --json flag …
```

The agent's `chimera/cli.py` edit added `--json` to ALL THREE
subcommands (`list`, `summary`, AND `clear`) — and shipped a test
(`test_escalations_clear_has_no_json_flag`) that asserts argparse
rejects `clear --json`. The agent self-contradicted. The witness
panel ran, saw the diff, and approved it. The operator caught the
violation at PR review and trimmed the change before merge (PR #3).

The v4.110 wiring was, on inspection, intact:

* `chimera/core/act.py:1632` calls `extract_charter_excerpts(witness_paths)`
  and passes the result through `review_with_panel(..., charter_excerpts=…)`.
* The witness prompt has a dedicated `## Charter excerpts` section
  with explicit check-#5 instructions for threshold-crossing rejection.

The bug was the **source** of `charter_excerpts`.
`extract_charter_excerpts` pulls the first 30 lines of each modified
`.py` file from HEAD — which works for the v13 shape (the
read-only-ish constraint was baked into `shell.py`'s own docstring)
but does NOT work for the v14 shape: `chimera/cli.py`'s docstring
says nothing about JSON-on-clear because that constraint was a
per-task assignment, not a file-level invariant. The CHARTER block
was technically present in `task_text`, but `task_text` is also the
full INBOX assignment paragraph, so the load-bearing language was
buried among six tasks and never surfaced under the dedicated
`Charter excerpts` header the panel is trained to anchor on.

## Decision

Add a second source for `charter_excerpts`: parse the INBOX `task_text`
for explicit charter blocks and lift them into the dedicated header.

`chimera/core/witness.py::extract_task_charter(task_text)` matches:

* any line containing the literal uppercase token `CHARTER`, plus
  the next `max_lines` (default 25) lines — the typical block shape
  used by soak runners' INBOX preambles;
* stand-alone prohibition lines (`MUST NOT`, `do NOT`, `NOT on`,
  `out of scope`, `shall not`, `are not allowed`, `forbidden`) plus
  ±1 line of context, when not already captured by a CHARTER block.

`chimera/core/act.py` concatenates `extract_task_charter(task_text)`
with `extract_charter_excerpts(witness_paths)` (task-charter first,
since the operator's wording is more specific to *this* task than
the file's general invariants) and passes the combined block through
to the panel.

The wiring stays exactly as v4.110 from that point on — same prompt
template, same check #5, same parallel cross-provider voting.

## Consequences

**Positive.**

* The v14 fixture diff (`--json` on `clear` despite explicit "NOT on
  clear" charter) is now reliably rejected by the panel in unit
  testing (`tests/test_witness_charter.py::test_v14_clear_json_violation_rejected_with_task_charter`).
* The v13 fixture (RAW_ALLOWLIST over-expansion anchored on the
  file's own docstring) continues to reject — v4.112 is additive,
  not a replacement.
* Soak runners that put load-bearing constraints in INBOX preambles
  (the natural authoring shape) get charter anchoring "for free"
  without having to also seed those constraints into file docstrings.

**Negative.**

* The extraction is heuristic: the uppercase `CHARTER` marker is
  load-bearing. A soak runner that writes "charter" lowercase will
  not trip the lift. This is a deliberate trade-off — the marker is
  explicit and cheap to write, and we'd rather under-extract than
  over-extract irrelevant task prose into the anchoring header.
* The prohibition-phrase fallback (`MUST NOT`, etc.) can pick up
  context-free advisory lines. The panel's check #5 still has to
  judge whether the diff crosses the named threshold; v4.112 only
  ensures the language is surfaced under the dedicated header,
  not that every surfaced line is actually load-bearing. False
  positives from over-extraction are softened by the unanimous-vote
  requirement (a single witness with judgment ignores noise).

**Neutral.**

* No change to panel composition (still 3-member cross-provider per
  v4.111), voting rule (still unanimous), or trigger scope (still
  `chimera/+tests/` writes only). The fix is strictly upstream of
  the panel.

## Alternatives considered

* **Move the charter into the file docstring at task-creation time.**
  Rejected: it requires every soak runner author to also be a code
  author for the target file, conflates per-task assignment with
  per-file invariant, and would leave stale "charter" comments in
  source after the task ships.
* **Pre-parse INBOX into a structured `charter:` YAML block.**
  Rejected for v4.112 as over-engineering; the free-text `CHARTER`
  marker is already what humans naturally write and is robust enough
  to match on. Worth revisiting if soak v15+ shows the heuristic
  missing cases that a structured field would catch.
* **Strengthen check #5 phrasing without changing sources.**
  Rejected: the v14 panel approved because the load-bearing language
  never reached the dedicated header in the first place. No amount
  of prompt-tone tuning fixes a missing input.

## References

* ADR 0106 (v4.102) — witness code review baseline
* ADR 0107 (v4.103) — cross-provider panel
* ADR 0110 (v4.110) — charter anchoring (file-docstring source)
* `chimera/core/witness.py::extract_task_charter`
* `tests/test_witness_charter.py` — `test_v14_*` fixtures
* PR #3 — the v14 operator-trimmed deliverable
* `scripts/archive/long_cycle_soak_v14.sh` — phase-2 INBOX (the v14 charter
  source-of-truth that v4.110 missed and v4.112 lifts)
