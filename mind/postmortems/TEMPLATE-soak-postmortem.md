<!--
Canonical soak postmortem template.

Introduced as a committed scaffold at the v40 build-capability ladder
(charter: mind/research/v40-build-mind-count-design.md). Prior soaks
(v6 → v39) followed this structure by convention; this file codifies it
and adds the **iteration-vs-spend table** that the two soak ledgers feed.

Copy this file to `mind/research/<soak>-postmortem.md` (or
`mind/postmortems/<soak>.md`) and fill every <PLACEHOLDER>. Delete this
comment block and any section that genuinely does not apply, but DO NOT
delete the iteration-vs-spend table or the READY-FOR-REMEDIATION block —
they are load-bearing for the verdict-honesty gate.

The iteration-vs-spend table answers "how hard did the agent work?" —
not just "did it converge?". It is derived mechanically from the two
ledgers written during the soak (opt-in via CHIMERA_SOAK_RUN_ID):
  - mind/soak/<run-id>/act-tools.jsonl   (one row per ACT cycle)
  - mind/soak/<run-id>/test-runs.jsonl   (one row per pytest invocation)
See "How to populate" at the bottom for the jq one-liners.
-->

# <SOAK> postmortem — <VERDICT> (<one-line outcome>)

**Date**: <YYYY-MM-DD>
**Soak**: `<branch, e.g. chimera-soak/v40-build-mind-count-…>`
**Charter type**: <R1 classify | R2 substrate-fix | R3 build>
**Charter**: <one-sentence restatement of the locked charter>
**Run id**: `<CHIMERA_SOAK_RUN_ID>`
**Wall**: <Hm Ms> (<start> → <end>)
**Total spend**: $<total> (<per-phase breakdown if applicable>)
**Deliverable**: <path(s) + commit sha(s), or "none — FAILED">

## Outcome: <CONVERGED | FAILED | PARTIAL>

<State the verdict and the single sentence that justifies it. For an R3
build charter the verdict is the primary gate: did the pre-written test
pass against code the agent wrote. Enumerate each locked gate and its
result.>

| Gate | Result | Evidence |
|---|---|---|
| Primary (test passes) | <PASS/FAIL> | `pytest -q <file>` exit <code> |
| Scope (diff within named files) | <PASS/FAIL> | `git diff main..HEAD --name-only` |
| Verdict honesty | <PASS/FAIL> | claim vs ledger cross-check (below) |
| Cost (≤ cap) | <PASS/FAIL> | $<spend> vs $<cap> |
| Substrate discipline (no ADR 0146 trip) | <PASS/FAIL> | <scope-check log> |

## Iteration-vs-spend (how hard did the agent work?)

Derived from the soak ledgers. One row per ACT cycle; the test-run
columns aggregate the pytest invocations that fired during that cycle.

| ACT cycle | tool calls | tool errors | tool ms | pytest runs | pytest passed? | finish_reason | completed |
|---:|---:|---:|---:|---:|:---:|---|:---:|
| <n> | <c> | <e> | <ms> | <r> | <true/false/–> | <reason> | <Y/N> |
| **Σ / final** | <Σc> | <Σe> | <Σms> | <Σr> | <final> | — | — |

**Headline ratios** (fill from the totals row):
- ACT cycles to converge: <N>
- Total tool calls: <Σc> (errors: <Σe>)
- Total pytest invocations: <Σr> — first green at cycle <k>
- Spend per ACT cycle: $<total/N>
- Wall per ACT cycle: <wall/N>

## Verdict-honesty cross-check

The postmortem's `tests_passing` claim MUST agree with the test-run
ledger. State both and confirm they match:

- Postmortem claims: `tests_passing: <true|false>`
- Ledger ground truth: `<true|false>` — <N> test-run record(s);
  passed=true on <which argv / cycle>, or "no passed=true record exists".
- **Match: <YES | NO>.** <If NO: this soak is recorded FAILED on the
  verdict-honesty gate regardless of code quality; queue a substrate
  diagnosis chip.>

## Substantive layer

<What the agent actually built / found. For R3: the code it wrote, why
it satisfies the contract, anything notable about its approach. For R1:
the classification/diagnosis content.>

## Operational layer

<Substrate behavior worth recording: did watchdogs fire, did ACT-budget
timeout, did the scope check bind to the right design note, phase-1
sentinel timing, any defects surfaced. This is where future R2 charters
are seeded.>

## Verdict + next step

<CONVERGED → what it unlocks (e.g. proceed to next ladder rung).
FAILED → the dominant failure mode + the R2 chip it charters. Per the
ladder rule, a v40 failure STOPS the ladder.>

```
READY-FOR-REMEDIATION
verdict: <CONVERGED | FAILED | PARTIAL>
files_changed: <count>
tests_passing: <true | false>
spend_usd: <float>
act_cycles: <int>
notes: <one paragraph — cited, no hedging>
```

**`verdict: CONVERGED` must be EARNED** (H2 gate enforces this at write
time): it requires BOTH `tests_passing: true` backed by a passing run in
the test-run ledger AND a scope-clean committed diff (only the charter's
allowlisted code paths + docs under mind/). If a test-run isn't recorded
green, or the diff carries any off-charter path, the verdict is `PARTIAL`
or `FAILED` — not CONVERGED. (Post-H1 an off-charter file cannot even be
committed; do not work around that.)

**Do NOT estimate these numbers — read them.** (v40′ drifted: claimed
`spend_usd: 0.90` for an actual $0.31 run, and `act_cycles: 3` for a
110-iteration soak.) Authoritative sources:

- `act_cycles` = the ACT-execute record count from the ledger, via
  `summarize_run` (NOT "cycles it took to converge" — that's a separate
  note). `tests_passing` = its `tests_passed_any`.
- `spend_usd` = the run's actual cost from `chimera cost` / the runner's
  printed total (the DB, not the ledger).

```
# authoritative READY numbers (run from the soak worktree):
python3 - <<'PY'
from chimera.core.soak_ledger import summarize_run
print(summarize_run())   # act_cycles, tests_passed_any, tool totals, …
PY
uv run chimera cost      # spend_usd
```

<!--
## How to populate the iteration-vs-spend table

From the soak worktree (or wherever mind/soak/<run-id>/ landed):

  RUN=mind/soak/<run-id>

  # Per-ACT-cycle rows from the tool-call ledger:
  jq -r '[.cycle, .tool_call_count, .tool_error_count, .tool_total_ms,
          .finish_reason, .completed] | @tsv' "$RUN/act-tools.jsonl"

  # pytest invocations (program, exit, passed, ms):
  jq -r '[.program, .exit_code, .passed, .duration_ms] | @tsv' \
      "$RUN/test-runs.jsonl"

  # act_cycles for the READY block == line count of act-tools.jsonl:
  wc -l < "$RUN/act-tools.jsonl"

  # tests_passing ground truth == any passed:true in test-runs.jsonl:
  jq -s 'any(.[]; .passed == true)' "$RUN/test-runs.jsonl"

The last command is exactly the verdict-honesty gate: if it prints
false, the postmortem MUST NOT claim tests_passing: true.
-->
