# ADR 0182 — Daily autonomous production (crawl/walk/run)

**Status:** Proposed (2026-06-12)

## Context

Chimera today runs only on operator request. Every soak/characterization
campaign is launched by hand, so there is no day-to-day change — which is
why a nightly LongMemEval/LoCoMo gate (ADR 0181) would burn spend measuring
a static benchmark against static code. The prerequisite the roadmap had
mis-ordered: **a nightly drift/quality measure only earns its keep once
Chimera is *producing* daily.** So the real question is how to make Chimera
productive on a daily basis first.

The machinery for autonomous production already exists and is tested:

- **Standing operation** — the loop supports daemon cadence
  (`CHIMERA_CYCLE_SECONDS`), not just one-shot `chimera run`.
- **Self-directed work** — Discovery/Curiosity/Reflection engines propose
  work and append it to `mind/INBOX.md` (`_append_proposals`, ADR 0094).
- **Trust-gated autonomous output** — `self_pr.py` opens *draft* PRs at
  T4+ under `CHIMERA_SELF_PR=1` (ADR 0163).
- **The safety envelope** — three cost caps (ADR 0072/0076/0079), scope
  checks (ADR 0146), the critic gate (ADR 0162), the trust ladder.

The missing piece is **a renewable, valuable, low-blast-radius source of
work**. Every campaign reused "fix N ruff findings from `chimera
self-scan`" because it is *reliable* — but ruff debt is finite and
shrinking, a characterization fixture, not a value stream. Engine
proposals are deliberately second-class (ASSESS sorts operator rows ahead,
ADR 0094) and trend toward governance busywork. Chimera can act daily; it
has nothing genuinely worth doing daily.

A second, equally real gap: every autonomy failure the soaks found —
scope creep (campaign cell 6), the gate-invisible task (2026-06-12 Finding
1: a DeprecationWarning "fix" that passed without editing the file),
journal-only commits (Findings 2–3, closed by #294) — was caught **because
a human was watching the run**. Unattended daily operation removes that
watcher, so the gates must hold alone.

## Decision

Adopt a **crawl → walk → run** program. Each phase is gated by the
operator on cost, quality, and performance before graduating; the
graduation criteria are explicit below.

### Phase 1 — CRAWL: curated-MD backlog, single repo, batch review

The work source is a folder of **operator-curated task specs** — Markdown
files the operator drops in, each a small, real, low-risk maintenance task.
Cadence: **one task per day** to begin.

- **Backlog location:** `mind/backlog/` (tracked, reviewable, easy to drop
  files into). A spec is a Markdown file with YAML frontmatter the existing
  `real_task_soak.sh` already consumes verbatim:

  ```markdown
  ---
  goal: One-line task description (→ TASK_GOAL)
  files: tests/test_x.py chimera/foo.py   # allowlist (→ TASK_FILES)
  test: tests/test_x.py                   # gate target (→ TASK_TEST), optional
  base: main                              # → TASK_BASE, optional
  ---
  Free-form context / acceptance notes for the agent.
  ```

- **Picker:** selects the oldest unclaimed spec (no matching open PR / no
  `done:` marker), validates the frontmatter, exports the env, and invokes
  the existing `real_task_soak.sh` unchanged. Reuses the whole soak spine
  — phase gates, scope check, watchdog, manual-handoff.

- **Output contract:** a **draft PR** the operator **batch-reviews**. Batch
  is the expedient starting point (narrow auto-merge is the Phase 3 target,
  not the Phase 1 one). One task/day ⇒ at most one PR/day to review.

- **Scope:** uberagent itself, where blast radius is smallest and the
  operator already reviews every change.

New code is small and additive: the spec format, the picker
(`chimera backlog next` / a thin wrapper), and a scheduled invocation. No
change to the loop, gates, or soak harness.

**Built (scaffold):** `chimera/core/backlog.py` (spec parse/validate/select,
fully unit-tested), the `chimera backlog list|validate|next` verbs (with
`next --check-gate` enforcing gate-visibility via `verify_at_ref` — exit 3
on a gate-invisible spec), the `mind/backlog/` folder + README + a worked
`done:true` example, and `scripts/crawl_daily.sh` — the one-task-per-run
driver that picks → gate-checks → runs `real_task_soak.sh` → draft PR, with
a dispatch log so a spec is not re-run before its PR lands.

**Live (2026-06-12):** the gate now accepts pytest flags in `test`
(`default_checks` tokenises `test_target`), so a deprecation under
`-W error` is a genuinely RED-on-base gate — which is what makes a
warning-only fix gate-visible on an otherwise-green repo. The backlog is
seeded with the two (and only two) gate-visible tasks the clean main
carries: the federation client deprecations (`streamablehttp_client`
rename; httpx `verify=<str>` → ssl context). The keyed scheduled runner is
provisioned on macOS via `scripts/crawl/install_launchd.sh`
(`com.chimera.crawl`, daily 09:15) → `scripts/crawl_daily.sh` → draft PR.
That a clean repo yields only two gate-visible tasks is the healthy signal;
the backlog grows as the operator curates work (and as WALK adds issues).

### Phase 2 — WALK: GitHub issues across elementalcollision repos

Swap the curated-MD source for live issues: triage/cluster (the
`oh-my-issues` skill), pick one inside a risk budget, draft a PR against
the right repo. Multi-repo, externally replenished, still batch-reviewed.
This is where the work source becomes genuinely self-renewing. The
curated-MD path stays available as the manual override.

**Built (ingestion, 2026-06-12):** `chimera/core/issue_backlog.py` +
`chimera backlog from-issues --repo <r> [--label crawl] [--dry-run]` turn a
*crawl-ready* issue (the `crawl` label + a fenced spec block in the body,
same fields as an MD spec) into a normal `mind/backlog/issue-<N>-<slug>.md`
spec with `issue: owner/repo#N` provenance. From there it flows through the
**same** picker, gate-visibility check, and soak — issues without a spec
block are skipped (not every issue is a gate-visible task), and the
gate-check still rejects an issue whose gate is already green. Issue
template: `.github/ISSUE_TEMPLATE/crawl-task.md`.

Deliberately **not yet** built (later increments): multi-repo PR
*targeting* (the soak builds against the local repo; a PR to a different
repo needs per-repo verify/soak adaptation), and free-form-issue triage
(`oh-my-issues` clustering an unstructured backlog into specs). The
ingestion is the renewable-source spine; these extend its reach.

**Skip-and-continue (fast-follow):** `backlog next --check-gate` now walks
the ready queue, skipping gate-invisible / base-errored specs (reported
per-spec) and dispatching the first that passes — so one mis-specified
issue no longer poisons the daily run. Exit 3 now means "candidates
existed but all were skipped" (distinct from 1 = empty backlog).

### Phase 3 — RUN: narrow auto-merge + production-health nightly

Graduate the safest change-classes (dependency bumps that pass full CI,
doc-only, lint) to **auto-merge** behind the trust ladder + an explicit
change-class allowlist; everything else stays batch-reviewed. *Now* the
**production-health nightly** is warranted — merge/revert ratio, gate-pass
rate, scope-adherence, cost-per-landed-change, ontology drift — aggregating
signals Chimera already emits (soak ledger, escalation memory, `chimera
cost`, drift detector). LongMemEval/LoCoMo stay a **release-time** gate
(run when memory-subsystem code changes), never a nightly.

**Built (measurement foundation, 2026-06-13):** `chimera health`
(`chimera/core/health.py`) — the CLI parity of the dashboard rollup:
cost-rate / drift / proposal-queue / hot-signature signals folded into a
worst-of `HEALTHY|WATCH|DEGRADED` verdict, `--json` for scripting, exit 1
on DEGRADED (`--fail-amber` to also fail on WATCH). Read-only; useful now
as an operator/CI heartbeat and the substrate a nightly will schedule.

**Built (evidence accrual, 2026-06-13):** the CRAWL **outcome ledger**
(`chimera/core/crawl_ledger.py`, `chimera crawl record|report|resolve`).
Each run records its outcome — slug, gate pass/fail, commits, cost,
branch, issue provenance, and an operator-set disposition
(pending/merged/reverted/abandoned). `crawl_daily.sh` parses the soak's
stable `[soak-outcome]` line into the ledger and logs a `chimera health`
snapshot per run. `chimera crawl report` folds it into the exact
graduation metrics — gate-pass rate, revert rate over landed work,
cost-per-run, cost-per-landed-change. This is the **evidence-first** path:
auto-merge stays gated until this ledger shows a sustained bar over real
landed PRs.

**Deliberately NOT yet built — gated, not forgotten:**
- *Auto-merge* is the highest-risk capability in the system and the
  graduation criteria gate it on **landed-PR evidence the ledger above now
  accrues** (zero CRAWL PRs have merged yet). It also needs the soak to
  actually open PRs — the existing `maybe_self_pr` (ADR 0163, trust-gated,
  default-OFF) is the seam, but flipping unattended merge on is
  unjustified until `chimera crawl report` shows a sustained quality bar.
- The *production-health nightly schedule* measures production volume that
  isn't being produced yet (clean repo, idle loop), so it is a template,
  not an active cron — same posture as the evals nightly.
- *WALK multi-repo targeting* (working the issues that live in
  claude-daemon / autoresearch-unified) is not a bounded increment: the
  soak is **chimera-self-improvement** end to end (worktrees the local
  repo, gates on `chimera verify`, runs Chimera's own loop). Targeting
  arbitrary repos is a different operating mode (Chimera as a general
  coding agent with per-repo verify) — a product decision + significant
  rework, not a fast-follow. *Free-form-issue triage* is downstream of it
  (chimera itself has zero open issues to triage).

## Hard prerequisites (block CRAWL going unattended)

1. **Gate-visibility.** A task must be unable to report "done" unless the
   gate observes a real red→green transition on the allowlist
   (2026-06-12 Finding 1). #294 closed the journal-only-commit half; the
   spec-picker must additionally reject specs whose gate cannot fail before
   the change (e.g. a warning-only task needs `-W error`), or verify the
   gate was red on `base` first.
   **Built:** `classify_gate_transition` + `chimera verify --base <ref>`
   (`chimera/core/repo_verify.py`) runs the gate on both the worktree and a
   throwaway base checkout and classifies red→green (exit 0) /
   gate-invisible green→green (exit 3) / still-red (exit 1). The CRAWL
   picker calls this at pick time; the soak phase-1 sentinel adopts it as a
   follow-up.

2. **A workable, understandable dashboard.** The dashboard had accreted to
   24 widgets across 4 telemetry presets — a debug console, not an
   operator's window. Batch review at one-human scale needs it to answer,
   at a glance: *what did Chimera do since I last looked, what is waiting
   for my review, and is production health trending bad?*
   **Built (first pass):** a new operator-first **Review** preset is now the
   default front door (`control-plane/app/page.tsx` + `CanvasShell` default).
   It leads with a **Production health** rollup (`lib/health.ts` +
   `ProductionHealthWidget`) — a worst-of verdict over the signals Chimera
   already emits (cost rate, drift, queue staleness, fragmentation, hot
   signatures, ontology audit), each dimension always showing its raw value.
   Chronicle answers "what did it do"; Inbox + Mutations are today's proxy
   for "what's queued" until the CRAWL phase adds the real PR-review queue.
   The 24 telemetry widgets and their presets are preserved, one click away.

## Graduation criteria (operator-gated)

- **CRAWL → WALK:** N consecutive days of one curated task → green draft PR
  with no scope creep and no gate-visibility miss; cost per landed task
  within budget; operator confidence in the batch-review loop.
- **WALK → RUN:** issue-sourced PRs sustain the same quality bar across
  multiple repos; a change-class is identified whose CI is trusted enough
  to auto-merge; the production-health metrics exist and are stable.

## Consequences

- The roadmap's "evals nightly" item is reclassified: the ADR 0181 gate is
  a release-time check; the genuine nightly is production-health, and it is
  a Phase-3 deliverable, not a near-term one.
- The keyed scheduled runner (operator will provision) is a Phase-1
  dependency but downstream of the gate-visibility fix.
- Embedding-routing (ADRs 0165/0166, backend = Ollama per ADR 0134 §6.b)
  remains gated on a *measured routing baseline*, which is itself a
  production-health metric — i.e. Phase 3, not before.

## Falsification / revisit triggers

- If curated MD tasks prove too sparse to sustain even one/day, accelerate
  to WALK (issues) rather than manufacturing busywork.
- If batch review at one/day already overloads the operator, that is the
  signal the dashboard/gate work must land before scaling cadence — do not
  raise the cadence to "look productive."
- If unattended CRAWL produces a single bad merge that the gates missed,
  halt and treat it as a gate-hardening incident before resuming.
