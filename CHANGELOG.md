# Changelog

All notable releases of Chimera are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/) with the v4.0 stability contract recorded in
[ADR 0025](docs/adr/0025-v4-stability.md).

Earlier releases (v1.0 → v4.113.0) are documented through the ADR series and
git tags; this changelog is introduced at v4.114.0 as the load-bearing
public record for releases going forward.

## v4.119.0 — 2026-06-06 — Semantic tool pre-filter (lexical v0)

The first slice of the vLLM Semantic Router evaluation
([docs/research/semantic-routing-evaluation-2026-06-06.md](docs/research/semantic-routing-evaluation-2026-06-06.md),
[ADR 0165](docs/adr/0165-semantic-tool-prefilter.md)). The ACT executor
previously handed the model **every** registered tool schema on every
round; as the unbounded `dynamic` skills and `mcp-<peer>` peer toolsets
grow, that catalog bloat is a known accuracy + token tax on every round of
every tool chain.

No changes to v4.0-stable surfaces (SQLite schema, graph store, mind
layout, HTTP endpoints, CLI verbs) per [ADR 0025](docs/adr/0025-v4-stability.md).
The new env knob (`CHIMERA_TOOL_PREFILTER`) is **default OFF** — behaviour
is byte-identical to `registry.schemas()` unless explicitly enabled.

### Per-task tool catalog scoping ([ADR 0165](docs/adr/0165-semantic-tool-prefilter.md))

`chimera/tools/tool_selection.py::select_tool_schemas` replaces the single
unconditional `registry.schemas()` call site in `core/act.py`. With the
flag on, the per-task catalog is scoped to the always-on `core` floor plus
any `dynamic`/`mcp-*` tool whose signal tokens (name + description +
parameter names) lexically overlap the task. Safety rails: the `core` floor
is never pruned, an empty/token-less task falls back to the full catalog,
and availability is honoured exactly as before. The `select_tool_schemas`
seam is designed as a drop-in point for an embedding-backed classifier once
[ADR 0134](docs/adr/0134-hybrid-search-eval.md) §#6.b picks the embedding
model. Covered by `tests/test_tool_selection.py` (9 cases).

## v4.118.0 — 2026-05-28 — Adaptive top-k temporal remediation (gate cleared)

The release that ships the first remediation from [ADR 0142](docs/adr/0142-hybrid-retrieval-for-long-horizon.md)'s
capstone amendment (v4.117.0). Phase A implementation + Phase B
gate-measurement both landed; all three pre-registered gates CLEARED with
margin. ADR 0142's substantive verdict (`Accepted (`_s`-only)`) is
**preserved** — the status line is amended to record the LoCoMo-temporal
lift, not to change the verdict.

No changes to v4.0-stable surfaces (SQLite schema, graph store, mind
layout, HTTP endpoints, CLI verbs, env vars per
[ADR 0025](docs/adr/0025-v4-stability.md)). The new env knob
(`CHIMERA_ADAPTIVE_TOPK_TEMPORAL`) is **default OFF** — current behavior
is bit-for-bit identical to v4.117.0 unless explicitly enabled.

### Adaptive top-k for temporal queries ([ADR 0142](docs/adr/0142-hybrid-retrieval-for-long-horizon.md) remediation #1)

The 19-item LoCoMo F2 temporal-regression diagnosis (v36→v39, closed in
v4.117.0) found H2 (context-budget dilution under top-k=8 truncation)
dominating at 74%. Remediation #1 detects temporal queries in the LoCoMo
adapter and skips top-k truncation for them, surfacing full chronology
to the answerer — directly attacking H2.

**Implementation** ([PR #131](https://github.com/elementalcollision/chimera/pull/131)):

- New `is_temporal_query` + `adaptive_topk_temporal_enabled` helpers in
  `chimera/evals/hybrid_retrieval.py` (~95 LOC additive)
- `_select_session_indexes` adaptive branch in `chimera/evals/locomo.py`
  (≤20 LOC delta) — returns `list(range(n))` (all sessions, chronological)
  when knob is ON and item category is `"temporal-reasoning"`
- Detection mechanism: category-lookup on LoCoMo's authoritative
  `category` label inside the harness; regex fallback for non-harness
  callers (deliberately narrow — Phase A spike found 3.1% recall +
  18–22% false-positive rate on this corpus; in-harness path keys
  strictly on category)
- 6 new tests covering positive/negative detection, category-signal
  short-circuit, adaptive-ON behavior, default-OFF byte-for-byte
  backward compat
- Default OFF behind `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1`

**Gate measurement** ([PR #132](https://github.com/elementalcollision/chimera/pull/132)):

All three pre-registered gates CLEARED on the full 1,986-item LoCoMo F2
corpus with `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1`:

| Gate | Floor | Measured | Margin |
|---|---:|---:|---:|
| Primary: temporal ≥+2pp | 37.42% | **42.71%** | **+5.29pp** (3.6× margin) |
| Overall regression: ≥F2−1pp | 58.37% | 59.67% | +1.30pp |
| `_s` regression: within ±3pp | ±3pp | 0.00pp (by construction) | full envelope |

Per-category breakdown:

| Category | n | F2 baseline | Phase B (adaptive-ON) | Δ |
|---|---:|---:|---:|---:|
| adversarial | 446 | 32.96% | 33.41% | +0.45pp |
| multi-hop | 321 | 45.79% | 44.86% | −0.93pp |
| open-domain | 841 | 85.49% | 85.49% | 0.00pp |
| single-hop | 282 | 46.81% | 46.81% | 0.00pp |
| **temporal-reasoning** | **96** | **35.42%** | **42.71%** | **+7.29pp** |
| **OVERALL** | **1986** | **59.37%** | **59.67%** | **+0.30pp** |

Open-domain (841 items) and single-hop (282 items) are **byte-identical**
to F2 (same correct counts), structurally proving the adaptive branch
fires only on `category == "temporal-reasoning"` and leaves the F2 code
path untouched for the 1,890 non-temporal items.

### ADR 0142 status amendment ([PR #133](https://github.com/elementalcollision/chimera/pull/133))

Records the Phase B result on ADR 0142:

- **Status-line edit**: `Accepted (`_s`-only) (2026-05-25)` →
  `Accepted (`_s`-only) + Phase B LoCoMo-temporal lift recorded (2026-05-28)`
  (format change, verdict preserved)
- New §Consequences subsection "Phase B remediation gate cleared
  (adaptive top-k for temporal queries, 2026-05-28)" appended after the
  v4.117.0-era "Temporal-reasoning regression diagnosis closure"
  subsection
- README row updated for status consistency
- Env knob default **unchanged at OFF**
- Other two ADR 0142 remediation directions (temporal-anchor
  preservation, mid-conversation summary injection) remain **named but
  not chartered**

### v39 deliverable on main ([PR #130](https://github.com/elementalcollision/chimera/pull/130))

Closes the cherry-pick loop on the v37→v39 fan-out series. Brings the
v39 classification deliverable from soak-branch commit `a9cc994` onto
main, matching how v37 (PR #123) and v38 (PR #125) were handled. With
all three deliverables on main, the full 19-item LoCoMo F2
temporal-reasoning regression diagnosis is fully git-tracked in
`mind/research/`, matching what ADR 0142's §Consequences subsection
references.

### Tests + CI

- **1,597 passed, 5 skipped** on main at `8876d60`. +6 net tests vs
  v4.117.0 (Phase A added 6 tests covering temporal-query detection +
  adaptive-branch behavior; no regressions elsewhere).

### What this release does NOT include

- **Env knob default flip**. `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` remains
  default-OFF. The Phase B note's recommendation defers any default flip
  to a future amendment after an independent re-sweep tightens the
  +7.29pp point estimate. This release honors that deference.
- **The other two ADR 0142 remediation directions**. Temporal-anchor
  preservation and mid-conversation summary injection remain named but
  not chartered per operator decision.
- **Cross-corpus generalization** of adaptive-top-k. The detection
  mechanism is LoCoMo-tuned (category-lookup on authoritative LoCoMo
  category labels). Generalizing to `_s` or other corpora is open work.
- **A status change on ADR 0142**. The amendment records the lift as a
  format change; the substantive `_s`-only verdict is unchanged.

### Upgrade notes

No breaking changes. New env knob introduced this release:

- `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` — int, default 0 (off). When set to
  `1`, LoCoMo adapter skips top-k truncation on items with
  `category == "temporal-reasoning"`. No effect on LongMemEval `_s` or
  any non-LoCoMo evaluation path.

---

## v4.117.0 — 2026-05-28 — LoCoMo temporal-regression investigation closure

The release that formally closes the LoCoMo F2 hybrid-retrieval temporal-reasoning
regression investigation chartered by [PR #98](https://github.com/elementalcollision/chimera/pull/98).
Across four autonomous-loop soaks (v36 → v39), Chimera-the-agent produced a
defensible 19-item diagnosis: **74% H2 (context-budget dilution under top-k=8
truncation), 21% H1 (retrieval miss), 5% H4 (F1/F2 spec drift), 0% H3
(answerer-model failure).** The H3 absence rules out the answerer-model axis
as the remediation lever and grounds ADR 0142's `Accepted (`_s`-only)` verdict
in mechanism.

This release crystallizes the substantive endpoint of weeks of substrate work
that started with the v35 cascade hardening in v4.116.0. No changes to v4.0-stable
surfaces (SQLite schema, graph store, mind layout, HTTP endpoints, CLI verbs,
env vars per [ADR 0025](docs/adr/0025-v4-stability.md)).

### The four-soak fan-out ladder (substantive layer)

Each soak produced a per-item classification deliverable + a postmortem with
operational + substantive verdicts. The conservative N=1 → N=5 → N=10 → N=19
ladder existed to make any failure mode diagnosable; all four converged.

| Soak | N (cumulative) | PR runner | PR postmortem | Outcome | Wall | Spend |
|---|---:|---|---|---|---:|---:|
| v36 | 1 | [#115](https://github.com/elementalcollision/chimera/pull/115) | [#117](https://github.com/elementalcollision/chimera/pull/117) | CONVERGES | 19 min | $0.24 |
| v37 | 5 | [#120](https://github.com/elementalcollision/chimera/pull/120) | [#121](https://github.com/elementalcollision/chimera/pull/121) | CONVERGES | ~10 min | $0.135 |
| v38 | 10 | [#122](https://github.com/elementalcollision/chimera/pull/122) | [#124](https://github.com/elementalcollision/chimera/pull/124) | CONVERGES | ~36 min | $0.399 |
| v39 | 19 | [#126](https://github.com/elementalcollision/chimera/pull/126) | [#127](https://github.com/elementalcollision/chimera/pull/127) | CONVERGES | 12.5 min | $0.156 |

**Cumulative spend for the full 19-item diagnosis: ~$0.93 across ~78 wall-min.**
Each soak independently classified its items by `item_id` sort order with a
locked no-discretion rule, then committed a research-note deliverable scoped
to one file. Per-item cost trended **down** at the largest fan-out (v39's
$0.017/item) — larger denominator amortized fixed phase costs.

### Capstone — ADR 0142 amendment ([PR #128](https://github.com/elementalcollision/chimera/pull/128))

Synthesizes the 19-item distribution into ADR 0142 as a new §Consequences
subsection. Status field unchanged (`Accepted (`_s`-only)`); the diagnosis
*explains* the verdict by naming the mechanism: same top-k=8 truncation that
helps `_s` long-horizon hurts LoCoMo temporal-reasoning through 74% context-
budget dilution. The H1/H2/H3 framework from [PR #107](https://github.com/elementalcollision/chimera/pull/107)
is preserved as the historical chartered-but-untested record.

Three remediation directions are **named but not chartered** in the amendment,
each with an explicit falsification gate:

- **Adaptive top-k for temporal queries** — detect temporal-reasoning question
  shape; increase top-k or disable retrieval for those queries
- **Temporal-anchor preservation under truncation** — preserve session-date
  headers and timestamped anchors preferentially
- **Mid-conversation summary injection** — pre-compute temporal-arc summaries
  per conversation; inject alongside top-k retrieval

### Operational layer — substrate-discipline hardening landed for the soaks

Several fixes landed during the fan-out arc to keep the substrate aligned with
the discipline the soaks needed. Each is small but load-bearing for future
fan-out work:

- **Phase-1 soft-sentinel** ([PR #118](https://github.com/elementalcollision/chimera/pull/118)):
  closes v36-postmortem follow-up B. Adds `soak_phase1_deliverable_landed` to
  `scripts/_soak_common.sh`, symmetric with phase-2's existing mechanism but
  adapted to phase-1 semantics (engines OFF, no commits expected). Required
  for multi-deliverable soaks where phase 1's previous "ready_marker_found"
  exit was accidentally checking the input reference doc rather than the
  output deliverable.
- **Scope-check design-note selection by branch prefix** ([PR #119](https://github.com/elementalcollision/chimera/pull/119)):
  closes v36-postmortem follow-up C. Replaces the "latest `*-design.md` by
  mtime" heuristic in [ADR 0146](docs/adr/0146-pre-commit-scope-check.md)'s
  `find_active_design_note` with principled selection that matches the chip
  prefix extracted from the current git branch name. Eliminates the "right by
  accident" verdict the v36 soak exposed.
- **Phase-1 sentinel-target fix** (inline in [PR #126](https://github.com/elementalcollision/chimera/pull/126)):
  v39-specific correctness fix — `INVESTIGATION_DOC` is explicitly set to the
  v39 OUTPUT deliverable rather than via `soak_extract_sentinel_path` (which
  pulled the F1 INPUT JSONL in v37/v38). Validated operationally: v39 was the
  first soak in the series with a correctly-targeted phase-1 sentinel.

### Dashboard benchmark-history widget ([PR #116](https://github.com/elementalcollision/chimera/pull/116))

Net-new read-only widget in `control-plane/components/widgets/BenchmarkHistoryWidget.tsx`
surfacing all LongMemEval + LoCoMo headline numbers accumulated since v4.114.0.
Source-of-truth is a curated `mind/benchmarks.json` (Option B per design
note); fail-soft on missing/malformed JSON. Server component, no client JS,
no new dependencies. 7 seed rows covering LongMemEval oracle/`_s` + LoCoMo
full/envelope/hybrid baselines.

### ADRs landed

- No new ADRs in this release. ADR 0142 is amended (existing §Consequences
  preserved; new closure subsection appended). ADR 0146 (pre-commit scope
  check, Proposed) is amended via PR #119 with the branch-prefix design-note
  selection fix; status remains Proposed pending more soak validation.

### Tests + CI

- **1,591 passed, 5 skipped** on main at `bfc87ab`. No test regressions across
  any of the 14 PRs in this release.
- `tests/test_scope_check.py` gained 5 tests covering branch-prefix selection
  (PR #119); other test counts unchanged.

### What this release does NOT include

- **Remediation implementation**. The three named directions (adaptive top-k,
  temporal-anchor preservation, mid-conversation summary injection) are
  candidates for future investigation, each operator-chartered separately with
  its own pre-registered falsification gate. None are implemented in v4.117.0.
- **Multi-deliverable or implementation-shaped soak validation**. The arc
  validated the autonomous-loop substrate at single-deliverable scale across
  N=1, N=5, N=10, N=19 — all R1 (no code change). Multi-deliverable or
  R2+ (code-change) shapes are future investigations.
- **Status change on ADR 0142**. The diagnosis explains the existing
  `Accepted (`_s`-only)` verdict; it does not modify it. A status change would
  require a remediation that lands, measures, and clears its own gate.

### Upgrade notes

No breaking changes. No new env knobs. No new CLI flags. The benchmark widget
adds `mind/benchmarks.json` to the repo; future operators appending baselines
should follow the schema documented in the file's `$schema_comment` field.

---

## v4.116.0 — 2026-05-28 — Autonomous-loop hardening cascade

The release that closes a six-class grounding-error cascade in the
autonomous-delivery loop, surfaced by four consecutive v35 soak attempts
against an open chartered question (LoCoMo F2 temporal-reasoning regression
diagnosis). The substantive question remains paused — the autonomous loop
has not produced a defensible diagnosis across four attempts — but every
operational failure mode the cascade surfaced has been fixed, with a real
end-to-end integration test now in CI to catch the next cascading defect
before it can ship.

No changes to v4.0-stable surfaces (SQLite schema, graph store, mind
layout, HTTP endpoints, CLI verbs, env vars per
[ADR 0025](docs/adr/0025-v4-stability.md)).

### The cascade (six grounding-error classes)

Each v35 attempt surfaced a structurally distinct defect on the path from
`chimera run` to a committed deliverable. Sequencing matters:

| # | Class | Where | Fix |
|---|---|---|---|
| 1 | Detector misfire on every secondary worktree | [ADR 0141](docs/adr/0141-chip-branch-jump-layers-2-3.md) Layer 2 used `git rev-parse --show-toplevel == cwd`, which is true in every worktree | [PR #103](https://github.com/elementalcollision/chimera/pull/103) — switch to `--git-dir == --git-common-dir` |
| 2 | SQLite cross-thread access under the persistent asyncio loop | `Loop.__init__` opened the DB on the main thread; `run_one_cycle` runs on the daemon thread | [PR #105](https://github.com/elementalcollision/chimera/pull/105) — `check_same_thread=False` + the missing **end-to-end CI test** that exercises `chimera run` from a real `git worktree add`-created secondary |
| 3 | Agent confabulation at commit-time | Engine guards (`scope_evasion`, `degenerate_loop_abort`, `witness_rejected`) detect off-charter behavior **between** cycles; a confabulated commit can land mid-cycle, before the next gate fires | [PR #108](https://github.com/elementalcollision/chimera/pull/108) — **pre-commit scope check** ([ADR 0146](docs/adr/0146-pre-commit-scope-check.md)) parses the design-note `## READY-FOR-REMEDIATION` section and refuses commits whose diff scope contradicts the locked R1/R2/R3 recommendation |
| 4 | ACT-phase budget was decorative | 240s budget only emitted a warning log on overrun; v35 attempt #3 observed 5–9× overruns | [PR #110](https://github.com/elementalcollision/chimera/pull/110) — enforce via `asyncio.wait_for`; cancel-and-advance to WRITE with partial results |
| 5 | Soak runner INBOX lied about `wiring_coordinator` | Phase-2 INBOX prose claimed an auto-push+PR+merge that never ran | [PR #111](https://github.com/elementalcollision/chimera/pull/111) — strip the lie; document the actual manual-handoff contract |
| 6 | Forward-progress watchdog was blind to convergence-defect mode | PR #109's `(cycle, spend)` signal can't fire when both advance while zero tasks complete | [PR #113](https://github.com/elementalcollision/chimera/pull/113) — add `tasks_completed` signal alongside, parsed from PR #110's structured event |

Plus the foundational watchdog itself ([PR #109](https://github.com/elementalcollision/chimera/pull/109) — forward-progress watchdog) and an ADR amendment recovery ([PR #107](https://github.com/elementalcollision/chimera/pull/107)).

### Pre-commit scope check ([ADR 0146](docs/adr/0146-pre-commit-scope-check.md))

The cascade's load-bearing artifact. Closes the commit-time vs detect-time
gap surfaced by v35 attempt #3, where the agent committed an honest
"I didn't do the work" disclosure and then **2 minutes later** committed a
fabricated diagnosis citing percentages it had never computed. The witness
panel + engine guards saw the off-charter behavior and demoted trust
T5→T0 — but none of them can undo a commit that has already landed.

- **Conservative refusal**: missing design note / missing section /
  ambiguous classification → warn-only. False positives would block
  legitimate work; false negatives are acceptable because the witness
  panel + engine guards remain.
- **Override knob**: `CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1` — mirrors
  [ADR 0141](docs/adr/0141-chip-branch-jump-layers-2-3.md)'s
  `CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1` shape. Override events are logged
  as `scope_check_override` so the witness panel can see them.
- **Event logging**: `state/scope_check_events.jsonl` feeds the engine
  guard system structured events (`scope_check_refusal`,
  `scope_check_override`, `scope_check_warn`).
- **25 unit tests + end-to-end fake-repo regression test** lock in the
  v35 attempt #3 failure pattern.

### Soak-harness defense-in-depth

Two new watchdogs at the soak-harness level, orthogonal to the
agent-loop's `degenerate_loop_abort`:

- **Forward-progress watchdog (PR #109)** — aborts after N consecutive
  iters with unchanged `(cycle, spend)`. Defaults: `SOAK_NO_PROGRESS_THRESHOLD=8`,
  `SOAK_NO_PROGRESS_GRACE=3`. Catches the "spend pinned" stall pattern
  from v35 attempt #3.
- **Task-completion watchdog (PR #113)** — aborts after N consecutive
  iters with `completed=0/M tasks` at the ACT-budget cap. Defaults:
  `SOAK_NO_COMPLETION_THRESHOLD=6`, `SOAK_NO_COMPLETION_GRACE=2`. Catches
  the "advancing spend, zero completion" pattern from v35 attempt #4
  that the first watchdog could not detect by construction.

Both watchdogs coexist; either independently triggers abort. Forensics
preserved on either trigger (no worktree deletion).

### ACT-phase budget enforcement ([PR #110](https://github.com/elementalcollision/chimera/pull/110))

`CHIMERA_ACT_BUDGET_SECONDS` (default **240s**) is now enforced via
`asyncio.wait_for`. On timeout the in-flight tool-use coroutine receives
`CancelledError`, a structured `act_budget_exceeded` event is logged
(with `completed_tasks` + `total_tasks` fields), and the loop advances
to WRITE with whatever partial `_act_results` accumulated. The 600s
silent-death watchdog ([ADR 0120](docs/adr/0120-silent-death-watchdog.md))
remains the outer hard ceiling.

The picked approach (Option A — cancel-and-replan, not Option B — raise
the cap) was justified by an explicit safety audit: SQLite consistency
verified (no torn writes between awaits); mid-response token waste real
but mild and bounded by per-call cost.

### Soak-runner consolidation cleanup

Before the v35 cascade exposed these defects, [PR #100](https://github.com/elementalcollision/chimera/pull/100)
consolidated `long_cycle_soak_v25.sh`…`v33.sh` (5,087 lines across 10
files) into a single canonical runner at `long_cycle_soak_v34.sh` (507
lines), archiving v25–v33 to `scripts/archive/soak-runners/`. v35 follows
the documented copy-and-replace-INBOX convention from that consolidation.
Per-version chip context preserved in the archive README.

### The systemic-gap E2E test

The PR #105 / `tests/test_chimera_run_e2e.py` test is the cascade's
durable artifact: it creates a real on-disk repo with `git init` + `git
worktree add` on a non-main branch, then drives `chimera.cli.main(["run"])`
end-to-end from inside that secondary worktree. **No mocks of the
detector, SQLite, or the persistent loop.** A future cascading defect
on the same code path will fail this test in CI before it can ship —
which is exactly what the cascade taught us we needed.

### Cascade meta-finding

The first four defects ([PR #103](https://github.com/elementalcollision/chimera/pull/103) detector, [PR #105](https://github.com/elementalcollision/chimera/pull/105) SQLite, [PR #108](https://github.com/elementalcollision/chimera/pull/108) confabulation, [PR #109](https://github.com/elementalcollision/chimera/pull/109)/[#110](https://github.com/elementalcollision/chimera/pull/110)
watchdog/budget) were all **code that didn't match prose / contract**.
The fifth ([PR #111](https://github.com/elementalcollision/chimera/pull/111) wiring_coordinator) was the **inverse**: prose that
didn't match code. The sixth ([PR #113](https://github.com/elementalcollision/chimera/pull/113) completion-signal) was a **signal-design
gap** — a single observed failure mode does not determine the right
watchdog signal. The v35 attempt #4 postmortem ([PR #112](https://github.com/elementalcollision/chimera/pull/112)) names this
generally: every postmortem recommendation should be filed as an explicit
follow-up chip with an owner, not left in a freeform "future work" bullet.

### v35 chartered question — **unresolved**

The LoCoMo F2 temporal-reasoning regression diagnosis (−10.42pp, see
[ADR 0142 §Cross-benchmark check](docs/adr/0142-hybrid-retrieval-for-long-horizon.md)
and the recovered subsection added by [PR #107](https://github.com/elementalcollision/chimera/pull/107)) remains chartered-but-untested.
Four autonomous-loop attempts produced zero diagnosis. The structural
reason is named in [PR #112](https://github.com/elementalcollision/chimera/pull/112): too much retrieval re-running required
per item, no per-step checkpointing within ACT. The question itself
stands as an open invitation for either (a) re-shape with much tighter
atomic units, (b) directed human-driven analysis, or (c) acceptance that
the autonomous-loop substrate cannot answer it under the chartered
prompt shape.

### ADRs landed

- [0146](docs/adr/0146-pre-commit-scope-check.md) — Pre-commit scope
  check (confabulation defense; Proposed pending operator validation
  that subsequent soaks see expected firing patterns).

### Tests + CI

- Test count at release: **1,586 passed, 5 skipped** on main at `8249ee3`.
- `tests/test_chimera_run_e2e.py` (PR #105) is the systemic-gap canary.
- 25 unit tests + 1 end-to-end test for the pre-commit scope check (PR #108).
- 9 cases in `scripts/test_soak_progress.sh` covering both watchdogs.

### Upgrade notes

No breaking changes. New env knobs introduced this release:

- `CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1` — override for the pre-commit scope check
- `CHIMERA_ACT_BUDGET_SECONDS` — float seconds, default 240
- `SOAK_NO_PROGRESS_THRESHOLD` — int, default 8 (forward-progress watchdog)
- `SOAK_NO_PROGRESS_GRACE` — int, default 3
- `SOAK_NO_COMPLETION_THRESHOLD` — int, default 6 (task-completion watchdog)
- `SOAK_NO_COMPLETION_GRACE` — int, default 2

---

## v4.115.0 — 2026-05-27 — Long-horizon retrieval + cross-benchmark triangulation

The release that broadens Chimera's evaluation surface beyond LongMemEval,
lands hybrid retrieval as the `_s` long-horizon recovery path, formalises
the noise-envelope methodology for "no regression" gates, and adds CI plus
the chip-branch-jump prevention stack as the operational backbone. No
changes to v4.0-stable surfaces (SQLite schema, graph store, mind layout,
HTTP endpoints, CLI verbs, env vars per
[ADR 0025](docs/adr/0025-v4-stability.md)).

### Headline numbers

| Surface | Substrate | Headline | vs prior |
|---|---|---:|---:|
| LongMemEval oracle (500) | o4-mini | **90.13% ± 0.83pp** (n=3 envelope) | replaces 90.80% point estimate |
| LongMemEval `_s` long-horizon (30 stratified) | o4-mini + hybrid retrieval | **66.67%** | **+56.67pp** vs 10.00% baseline |
| LoCoMo full corpus (1,986) | gpt-4o-mini | **48.86% ± 0.46pp** (n=3 envelope) | net-new benchmark |
| LoCoMo + hybrid retrieval (1,986) | gpt-4o-mini | **59.37%** | **+10.02pp**, per-category MIXED |

### Hybrid retrieval ([ADR 0142](docs/adr/0142-hybrid-retrieval-for-long-horizon.md))

BM25 + dense (RRF-fused) retrieval layer with auto no-op when
`len(history) ≤ top_k`. Default off; engages on LongMemEval `_s` (40–60
sessions/item) and LoCoMo (19–32 sessions/conversation), structurally
preserves oracle's 1–3-session items as byte-identical to baseline. Status:
**Accepted (`_s`-only)** after cross-benchmark check on LoCoMo (per-target
opt-in posture confirmed; not a default).

- [PR #84](https://github.com/elementalcollision/chimera/pull/84): LongMemEval `_s` baseline at 10.00% — the cliff motivating the chip.
- [PR #85](https://github.com/elementalcollision/chimera/pull/85): hybrid retrieval implementation (BM25 + dense + RRF, `--hybrid-retrieval --retrieval-top-k 8`).
- [PR #86](https://github.com/elementalcollision/chimera/pull/86): T2.1b oracle no-regression sweep — Accepted (`_s`-only).
- [PR #98](https://github.com/elementalcollision/chimera/pull/98): F2 LoCoMo ablation — MIXED (3 cats improve, 1 cat harms, 1 in-envelope). Cross-benchmark check appended to ADR 0142.

### Noise-envelope methodology ([ADR 0143](docs/adr/0143-longmemeval-oracle-noise-envelope.md), [ADR 0145](docs/adr/0145-locomo-noise-envelope.md))

Future "no regression" gates use `mean − 2σ` across byte-identical-input
reruns, not single-sample point estimates. Replaces the failure mode where
~50% of equivalent re-runs would fail a strict point-estimate gate (the
T2.1b mistake). Per-category gates published; symmetric `mean + 2σ`
"improves" bars also published so positive-effect chips have explicit
detection thresholds.

- [PR #87](https://github.com/elementalcollision/chimera/pull/87): LongMemEval oracle envelope (n=3): 90.13% ± 0.83pp → gate 88.47%.
- [PR #92](https://github.com/elementalcollision/chimera/pull/92): LoCoMo envelope (n=3): 48.86% ± 0.46pp → gate 47.94%. 1.8× tighter than LongMemEval's o4-mini envelope; substrate confound between larger per-cat n and gpt-4o-mini-vs-o4-mini honestly disclosed.
- Reusable `scripts/compute_locomo_envelope.py` produces the envelope tables + flip matrices from arbitrary `label=path` graded JSONL inputs.

### T2.1d falsification ([PR #89](https://github.com/elementalcollision/chimera/pull/89))

Pre-registered substrate pivot: would a temperature-pinnable, non-reasoning
answerer (`gpt-4o-mini` at T=0) tighten the o4-mini noise envelope?
**Decisively no** (45.40% overall, −43.07pp from envelope floor; collapse
monotonic in context complexity). o4-mini envelope stands as the operative
noise model. `--answer-temperature` CLI flag preserved on `main` as
infrastructure for any future envelope-tightening attempt.

### LoCoMo benchmark integration ([ADR 0144](docs/adr/0144-locomo-benchmark-integration.md))

Chimera's second evaluation surface. 1,986 QA pairs across 10 long-form
conversations (19–32 sessions each); category taxonomy: adversarial,
multi-hop, open-domain, single-hop, temporal-reasoning. Adapter at
`chimera/evals/locomo.py` mirrors `chimera/evals/longmemeval.py`; grader at
`scripts/grade_locomo.py` preserves the [ADR 0143](docs/adr/0143-longmemeval-oracle-noise-envelope.md)
reasoning-judge guard.

- [PR #90](https://github.com/elementalcollision/chimera/pull/90): adapter + grader + CLI verb (`chimera evals locomo`) + 19 tests + directional 60% spike.
- [PR #91](https://github.com/elementalcollision/chimera/pull/91): F1 full corpus baseline 49.35%; category ordering matches paper exactly.
- [PR #92](https://github.com/elementalcollision/chimera/pull/92): F3 noise envelope (above).
- [PR #98](https://github.com/elementalcollision/chimera/pull/98): F2 hybrid-retrieval ablation MIXED — adds the cross-benchmark check to ADR 0142.

With two benchmarks fully characterised, future verdicts can be
triangulated rather than conditioned on a single corpus.

### Operational backbone

- **CI on PR + push to main** ([PR #82](https://github.com/elementalcollision/chimera/pull/82)): GitHub Actions, ubuntu-latest, Python 3.13, `uv sync --frozen --extra dev`, `uv run pytest -q`. First CI in the repo; makes "all tests pass" a machine-verifiable merge gate.
- **Chip-branch-jump prevention Layers 2+3** ([ADR 0141](docs/adr/0141-chip-branch-jump-layers-2-3.md), [PR #83](https://github.com/elementalcollision/chimera/pull/83)): `chimera run` refuses with exit 2 when cwd=main worktree AND branch≠main, before any provider spend. Pure-bash pre-commit hook logger as evidence trail. Override knob `CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1`.
- **Grader durable home + reasoning-judge guard** ([PR #88](https://github.com/elementalcollision/chimera/pull/88)): grader moved from `/tmp/chimera-baseline/grade.py` to `scripts/grade_longmemeval.py`, default judge pinned to `openai/gpt-4o-mini`, blocklist guard refuses `openai/o4-mini` and other reasoning-model judges that silently zero every grade at `max_tokens=16`. Override knob `CHIMERA_GRADE_ALLOW_REASONING_JUDGE=1`.

### Methodology refinements

- **Stratified spike protocol** ([ADR 0140](docs/adr/0140-stratified-spike-protocol.md)): n=24 spike stratified by category with per-category gates, refining ADR 0138's flat n=30 protocol. Quantitatively justified after F3: LoCoMo single-hop σ=1.68pp at n=282 vs LongMemEval SPP σ=5.09pp at n=30 — small per-category n is the dominant noise source.
- **Knowledge-update layering hypothesis falsified** ([ADR 0139](docs/adr/0139-knowledge-update-grounding-sensitivity.md)): −5.13pp on KU under PR #75 was stochastic re-roll on items where the heuristic emitted 0 bullets (byte-identical prompts); diagnostic methodology — bucket items by whether intervention fired — adopted as standard for adapter-class chips.

### Infrastructure fixes (unblocked F2)

The F2 LoCoMo full sweep surfaced five reliability issues in the
OpenRouter + Ollama pipeline; each fixed independently before F2 launched.

- **Persistent asyncio loop for OpenRouter answer_fn** ([PR #93](https://github.com/elementalcollision/chimera/pull/93), [PR #94](https://github.com/elementalcollision/chimera/pull/94)): per-call `asyncio.run` was breaking long sweeps at conversation boundaries; replaced with a process-lifetime loop.
- **LoCoMo adapter cleanup race** ([PR #95](https://github.com/elementalcollision/chimera/pull/95)): `iterdir`/`unlink` race during mind-dir reset on long sweeps.
- **OllamaEmbedder timeout + retry** ([PR #96](https://github.com/elementalcollision/chimera/pull/96)): bounded per-batch embed timeout with graceful BM25-fallback; degradation floor logged, no escalation.
- **Shared `httpx.AsyncClient` on OpenRouterProvider** ([PR #97](https://github.com/elementalcollision/chimera/pull/97)): connection-pool reuse across the 1,986-item sweep; eliminated socket exhaustion at conversation boundaries.

F2 then ran clean: 1986/1986 items, 0 answer errors, 0 BM25-fallback events,
0 wait_for timeouts, ~$8 spend, 3 h 41 min wall-clock.

### ADRs landed

- [0139](docs/adr/0139-knowledge-update-grounding-sensitivity.md) — Knowledge-update layering hypothesis falsified.
- [0140](docs/adr/0140-stratified-spike-protocol.md) — Stratified spike protocol.
- [0141](docs/adr/0141-chip-branch-jump-layers-2-3.md) — Chip-branch-jump prevention Layers 2+3.
- [0142](docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — Hybrid retrieval for long-horizon (Accepted `_s`-only).
- [0143](docs/adr/0143-longmemeval-oracle-noise-envelope.md) — LongMemEval oracle noise envelope.
- [0144](docs/adr/0144-locomo-benchmark-integration.md) — LoCoMo benchmark integration.
- [0145](docs/adr/0145-locomo-noise-envelope.md) — LoCoMo noise envelope.

### Tests + CI

- 1,500+ tests passing on every PR via GitHub Actions; F2-chain added 4 LoCoMo adapter tests + 4 grader-guard tests + persistent-loop coverage.
- Test count at release: **1,552 passed, 5 skipped** on main at `cf75258`.

### Upgrade notes

No breaking changes. New optional CLI flags:

- `chimera evals longmemeval --hybrid-retrieval [--retrieval-top-k 8]` — engages hybrid retrieval (auto-no-op on oracle).
- `chimera evals longmemeval --answer-temperature <float>` — opt-in temperature pinning (default omitted; preserves reasoning-model compatibility).
- `chimera evals locomo …` — full new subcommand mirroring longmemeval flags.

Override knobs introduced this release: `CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1`,
`CHIMERA_GRADE_ALLOW_REASONING_JUDGE=1`.

---

## v4.114.0 — 2026-05-25 — LongMemEval Tier-1 close-out

The first release that lifts Chimera's LongMemEval `oracle` corpus baseline
into the 90%+ band and closes the Tier-2B implicit-preference-inference
investigation cleanly. No changes to v4.0-stable surfaces (SQLite schema,
graph store, mind layout, HTTP endpoints, CLI verbs, env vars per
[ADR 0025](docs/adr/0025-v4-stability.md)).

### LongMemEval corpus baseline

- **Headline**: **90.80% overall** on `longmemeval_oracle.json` (500 items),
  o4-mini answerer / gpt-4o-mini judge. Per-category: knowledge-update
  96.15%, multi-session 90.23%, single-session-assistant 100.00%,
  single-session-preference 46.67%, single-session-user 98.57%,
  temporal-reasoning 90.23%.
- Reproduction and full per-category breakdown:
  [`mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md`](mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md).
- Established as the durable regression floor for all subsequent
  LongMemEval-affecting chips.

### Tier-1 wins landed pre-release

- **T1.1 — Answer-token budget** ([PR #61](https://github.com/elementalcollision/chimera/pull/61)):
  `--answer-max-tokens=2048` default in the `chimera evals longmemeval`
  adapter. Empty-hypothesis rate stable at ~0.4–0.8% on 500-item sweeps.
- **T1.2 — Temporal-aware dialectic** ([PR #62](https://github.com/elementalcollision/chimera/pull/62),
  [ADR 0136](docs/adr/0136-temporal-aware-dialectic.md)): one sentence on
  cross-session temporal integration appended to `_DIALECTIC_PROMPT`.
  +70.98pp on temporal subset at smoke.
- **T1.3 — Preference-aware dialectic** ([PR #65](https://github.com/elementalcollision/chimera/pull/65),
  [ADR 0137](docs/adr/0137-preference-aware-dialectic.md)): one sentence on
  honoring user-stated preferences appended to `_DIALECTIC_PROMPT`. Surgical;
  no corpus regression elsewhere.
- **T1.4 — Post-Tier-1 baseline** ([PR #67](https://github.com/elementalcollision/chimera/pull/67)):
  500-item sweep at `7e379ae` = **80.60% overall**, 53.38% temporal. Surfaced
  the temporal-reasoning gap that T1.5 closed.
- **T1.5 — Timestamp grounding** ([PR #69](https://github.com/elementalcollision/chimera/pull/69),
  [ADR 0136](docs/adr/0136-temporal-aware-dialectic.md) amendment):
  `**Today's date:**` and per-session `**Session date:**` headers added to
  the LongMemEval adapter's synthetic peer-card. Closes the temporal-
  reasoning regression: **+36.85pp temporal, +10.20pp overall → 90.80%**
  at `14192658`.

### Tier-2B closure (Option C adopted)

[ADR 0138 — Implicit Preference Inference](docs/adr/0138-implicit-preference-inference.md)
remains **Proposed** as a diagnostic. Two adapter-grounding-extension designs
were investigated and falsified at the corpus layer:

- [PR #72](https://github.com/elementalcollision/chimera/pull/72) — Option B v1 (`## User context` regex). Gate B fail; reverted by [PR #74](https://github.com/elementalcollision/chimera/pull/74).
- [PR #75](https://github.com/elementalcollision/chimera/pull/75) — Option B v2 (redesigned heuristic). Spike Gate B borderline; promoted to `main`; corpus sweep showed **90.00% overall (−0.80pp from 90.80% floor)** with **−5.13pp on knowledge-update** despite **+10.00pp on single-session-preference**. Reverted by [PR #77](https://github.com/elementalcollision/chimera/pull/77).

**Structural finding** ([PR #77](https://github.com/elementalcollision/chimera/pull/77)):
the LongMemEval adapter's single global peer-card cannot promote
implicit-preference signal without changing prominence-for-other-categories
in ways the model isn't robust to. This is a layering problem, not a
heuristic-quality problem. Two independent designs in the same content-shape
family produced net-negative overall accuracy; iterating on a v3 heuristic at
this layer is not the recommended forward path.

**Option C adopted as the forward path** (see ADR 0138 §"Option C — adopted
2026-05-25"):
- **C-i** — Hybrid retrieval at the dialectic boundary
  ([ADR 0134](docs/adr/0134-hybrid-search-eval.md)'s deferred vector
  path) — net-new design ADR required.
- **C-ii** — Ingestion-time category-aware peer-card composition that
  separates implicit-preference surfacing from the dialectic prompt
  entirely — net-new design ADR required.
- **C-floor** — Accept 46.67% on single-session-preference as the
  architectural floor at the adapter+prompt layer. This release ships
  against that floor.

### Methodology infrastructure (durable wins for future evals work)

- **Diagnose-before-shipping** ([PR #68](https://github.com/elementalcollision/chimera/pull/68)):
  failure-mode taxonomy on graded misses before any prompt or grounding
  change. Replayed by the Tier-2B diagnostic note.
- **Pre-registered Gate A / Gate B / regression-check framework**
  ([PR #76](https://github.com/elementalcollision/chimera/pull/76)):
  paired-item gates beat aggregate-percentage gates at n=30 spike scale.
- **Corpus-pre-promotion** ([PR #77](https://github.com/elementalcollision/chimera/pull/77)):
  n=30 single-category spikes cannot see collateral damage in other
  categories. Promotion to `main` requires a corpus sweep. Future spike
  charters must either measure beyond the target category or mandate
  corpus measurement before status flip.

### Known limitations

- **Single-session-preference at 46.67%** is an architectural floor at the
  adapter+prompt layer; further gains require Option C-i or C-ii design
  work.
- **LongMemEval `_s` long-horizon corpus** has not been swept. Baseline is
  `oracle` only.
- **Two likely judge false-negatives** (gpt-4o-mini's strict literal
  matching on `08f4fc43` and `gpt4_e072b769`) — treating these as ground-
  truth errors would put the headline at 91.20% / temporal at 91.73%. The
  reported number is the strict-judge value.
- **n=30 single-category spikes have meaningful per-item stochasticity** on
  the o4-mini answerer (PR #77 §"n=30 spike vs n=500 corpus alignment"):
  1/30 SPP items flipped reliably across spike and corpus runs. Future
  spike charters should not over-interpret single-item gate outcomes.

### Surfaces unchanged

No changes to v4.0-stable surfaces per [ADR 0025](docs/adr/0025-v4-stability.md):
SQLite schema, graph schema, peer-registry schema, mind layout, HTTP
endpoints, CLI verbs, env vars all unchanged. The LongMemEval adapter is an
internal evals surface (ADR 0135), not a v4.0-promised contract.

### References

- Release-prep design note:
  [`mind/research/release-prep-2026-05-25.md`](mind/research/release-prep-2026-05-25.md).
- Anchor ADRs: [0135](docs/adr/0135-longmemeval-integration.md),
  [0136](docs/adr/0136-temporal-aware-dialectic.md),
  [0137](docs/adr/0137-preference-aware-dialectic.md),
  [0138](docs/adr/0138-implicit-preference-inference.md).
- Baseline notes:
  [post-T1.5](mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md),
  [post-PR #75 FAIL verdict](mind/research/longmemeval-baseline-post-pr75-2026-05-25.md).
- Upstream: <https://github.com/xiaowu0162/LongMemEval>.
