# v43 design — R3 build-capability, parallel fan-out (N=3 independent builds, one soak)

**Date locked**: 2026-05-29
**Charter type**: R3 build (ladder rung 4, the final rung; v40′/v41/v42 cleared rungs 1–3)
**Branch prefix**: `chimera-soak/v43-trio-*` (token `v43`)
**Scope-check binding**: prefix `v43` matches this `v43-*-design.md` (ADR 0146 + PR #119).

## Why v43 exists — and what it changes vs v42

v40′ (tiny), v41 (moderate edge cases), and v42 (multi-file + authored import
boundary) all cleared cleanly and cheaply. Build capability is established for
a **single cohesive deliverable** per soak. v43 is the last rung: it scales the
**fan-out breadth** to **three independent build targets in one soak**.

**Deliberate experimental design — change ONE variable.** v42 already proved
the agent can coordinate a cross-file import boundary, so v43 keeps each of its
three targets a **single, self-contained file** (no import boundary, no shared
code). The only thing escalated from v42 is N: 1 deliverable → 3 independent
deliverables. That isolates the new question:

> Does the substrate hold when the loop must select, build, verify, commit, and
> honestly report on **three independent build charters across one soak** —
> without dropping a task, conflating two targets, mis-binding a scope check,
> or letting one task's failure contaminate another?

The new stresses this rung probes (none exercised at N=1):

1. **Task management at N=3.** The INBOX seeds three independent build tasks.
   The planner/queue and the three-strikes/forward-progress watchdogs must let
   the agent finish all three across cycles, not livelock on one or drop two.
2. **Multi-target scope allowlist.** One design note now lists **three**
   backticked code paths → allowlist `{strcase.py, numfmt.py, seqstats.py}`.
   Each per-module commit stages only its own file; ADR 0146 `classify_diff`
   must accept each (staged ⊆ allowlist) without demanding all three at once.
3. **Three independent commits**, each `[agent]`-prefixed, each passing the
   per-commit scope + index-bypass (H1) gates independently.
4. **Three READY blocks, three honesty checks.** Each module gets its own
   postmortem with a READY-FOR-REMEDIATION block. The post-v42 numeric-honesty
   gate (Rules A–E: `tests_passing`, `verdict`, `act_cycles`, `spend_usd`) now
   checks **each** at write time — the hardening that was landed precisely
   because three postmortems are too many to hand-audit.
5. **Trust continuity across tasks.** Completing task 1 should not leave trust
   degraded into task 2; a failure on one target should be locally contained.

Same isolation discipline as every prior rung: all three targets are brand-new
modules nothing imports at load time, tested directly (no CLI, no driver
coupling), so a regression in any one cannot brick `chimera run` or the other
two builds.

## The three targets (THREE new single files, mutually independent)

Each is a pure-function module of v40′/v41-tier difficulty. No target imports
another; no target imports existing Chimera code. Chosen so the three contracts
are obviously distinct (no chance of conflation) yet comparable in size.

### 1. `chimera/strcase.py` — string-case conversion

    def to_snake(s: str) -> str: ...
    def to_camel(s: str) -> str: ...

- `to_snake`: insert `_` before any uppercase that is **preceded by a
  lowercase letter or digit**, then lowercase all (the simple, unambiguous
  rule — no acronym special-casing, to keep the target tiny-tier).
  `"CamelCase"` → `"camel_case"`; `"HTTPServer"` → `"httpserver"` (no interior
  uppercase has a lowercase predecessor); `""` → `""`; already-snake unchanged.
- `to_camel`: split on `_`, lowercase the first part, title-case the rest, join.
  `"camel_case"` → `"camelCase"`; `""` → `""`; single token unchanged.

### 2. `chimera/numfmt.py` — numeric formatting

    def human_bytes(n: int) -> str: ...
    def clamp(x: float, lo: float, hi: float) -> float: ...

- `human_bytes`: binary units `B, KiB, MiB, GiB`; one decimal for non-byte
  units, no decimal for bytes. `0` → `"0 B"`; `1536` → `"1.5 KiB"`;
  `1048576` → `"1.0 MiB"`. (Locked thresholds/rounding in the test.)
- `clamp`: return `x` bounded to `[lo, hi]`. `clamp(5,0,10)`→`5`;
  `clamp(-1,0,10)`→`0`; `clamp(99,0,10)`→`10`.

### 3. `chimera/seqstats.py` — sequence statistics

    def running_max(values: list[int]) -> list[int]: ...
    def dedupe_stable(values: list[int]) -> list[int]: ...

- `running_max`: cumulative maxima. `[3,1,4,1,5]` → `[3,3,4,4,5]`; `[]` → `[]`.
- `dedupe_stable`: drop later duplicates, preserve first-seen order.
  `[3,1,3,2,1]` → `[3,1,2]`; `[]` → `[]`.

> The pre-written tests are the authoritative spec for every boundary above;
> any prose/`-> str` discrepancy resolves to the test.

## What Chimera may touch (hard cap)

- `chimera/strcase.py` — new module (CREATE).
- `chimera/numfmt.py` — new module (CREATE).
- `chimera/seqstats.py` — new module (CREATE).
- `tests/test_strcase.py`, `tests/test_numfmt.py`, `tests/test_seqstats.py` —
  READ-ONLY (already on main); read to discover each contract; MUST NOT edit.

`chimera/cli.py` and every other existing source are out of scope.

## READY-FOR-REMEDIATION

<!--
ADR 0146 locked-recommendation parsed by the pre-commit scope check
(branch prefix v43 -> this v43-*-design.md). Worded to contain no
code-forbidding signal phrase (see _NO_CODE_RE). THREE backticked code paths
-> allowlist {chimera/strcase.py, chimera/numfmt.py, chimera/seqstats.py}. The
three tests are NOT backticked, so a staged edit to any is refused at commit
time. Files under mind/ and .md files are auto-allowed.
-->

R3 build, parallel fan-out N=3. The allowed code paths for this charter are
`chimera/strcase.py`, `chimera/numfmt.py`, and `chimera/seqstats.py` — three
independent single-file modules the agent creates, one per build task. The
three pre-written tests under tests/ are read-only input and are deliberately
excluded from this allowlist; any staged edit to them is refused at commit
time. The three postmortem deliverables and other files under mind/ are
auto-allowed. Each commit uses the `[agent]` prefix and stages only its own
module.

## Pre-written tests (strict-mode probes — one per target)

`tests/test_strcase.py`, `tests/test_numfmt.py`, `tests/test_seqstats.py` land
on main FAILING (modules absent), each gated by `CHIMERA_V40_GATE`: default CI
→ skipped; under the gate, pre-impl → failed, post-impl → passed. Each uses the
lazy-import harness (`ImportError` → clean assertion failure, N failed / 0
errors). The three are mutually independent — a build that completes only one
target leaves the other two test files red.

## Falsification gates (locked on approval — no post-hoc relaxation)

1. **Primary (×3)**: each of `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q
   tests/test_{strcase,numfmt,seqstats}.py` → exit 0, all pass. ALL THREE must
   pass; two-of-three is a FAILED rung (partial fan-out is the failure mode).
2. **Scope**: `git diff main..HEAD --name-only` ⊆ {the three modules + the
   three postmortems}; and per-commit, each commit's staged set ⊆ the allowlist.
3. **Verdict-honesty (×3)**: each postmortem's `tests_passing` / `verdict` /
   `act_cycles` / `spend_usd` pass Rules A–E against ground truth (enforced
   in-loop; this is the substrate the drift chip hardened for exactly N=3).
4. **Cost**: total ≤ **$6.00** ($2.00/build — 3× v42's envelope, generous for
   postmortem churn; still a hard rolling-hour-bounded cap).
5. **Substrate-discipline**: no ADR 0146 trip; H1/H2/H3 + B1/B2 + numeric
   honesty all live in the loop; no task dropped or conflated (all three
   targets attempted and reported).

## Runner (build step — NOT yet written)

`scripts/long_cycle_soak_v43.sh` — clones the v42 runner and adapts it for N=3:

- **Three build targets / three tests / three allowlist paths.** Phase-2
  staging is per-module (three independent commits), not one combined stage.
- **Phase-1 soft-sentinel for N=3.** Phase 1 is "done" only when ALL THREE
  gated tests pass AND three postmortems exist — the sentinel's done-condition
  must AND across three (target, test) pairs, not one. This is the main runner
  change and should be unit-tested before launch (a sentinel that trips on the
  first green test would end phase 1 with two targets unbuilt).
- **INBOX seeds three independent, cohesive build tasks** (one per module),
  each self-contained per the v40-#2 lesson (a fragmented checklist decoupled
  build from verification). ACT budget 600s/cycle as for prior builds.
- Run id `v43-trio-$STAMP`, prefix `v43`. Inherits the full hardened scaffold.
  **Launch is a separate explicit operator action (PR #111 manual-handoff).**

## Locked decisions (operator-approved 2026-05-29)

1. **Three postmortems** — one per module, so each verdict is independently
   honesty-checked (Rules A–E) and a per-target FAILED is localized. Worth the
   extra writeup churn for separable falsification records.
2. **Cost cap $6.00** ($2.00/build) — rolling-hour-bounded hard cap.
3. **Single-file per target** — each module stays tiny/moderate tier; the only
   variable escalated from v42 is the fan-out breadth N. No per-target depth
   increase (that would confound two variables).

## Ladder position

| rung | soak | result |
|---|---|---|
| 1 tiny | v40′ | CLEARED ($0.31) |
| 2 moderate | v41 | CLEARED ($0.137) |
| 3 multi-file | v42 | CLEARED ($0.16) |
| 4 parallel (N=3) | **v43** | this charter (LOCKED) |

A clean v43 convergence closes the build-capability ladder: it would show the
loop can carry multiple independent build charters end-to-end on a fully
honesty-gated substrate. A failure is a substantive signal about task
management / isolation under fan-out — and the substrate gets hardened, as at
every prior rung.

## On approval — the build sequence (each a reviewable chip)

1. Write the three pre-written tests (`tests/test_{strcase,numfmt,seqstats}.py`)
   — land on main FAILING-under-gate / SKIPPED-in-CI (the v40-family pattern).
2. Lock this design note (resolve the three open questions, drop the DRAFT
   marker) and land it with the tests.
3. Write + unit-test `scripts/long_cycle_soak_v43.sh` (esp. the N=3 phase-1
   sentinel done-condition).
4. PAUSE for the explicit launch go-ahead.
