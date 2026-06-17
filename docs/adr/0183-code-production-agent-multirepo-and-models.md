# ADR 0183 — Chimera as a code-production agent: multi-repo reach + code-model ingestion

**Status:** Proposed (2026-06-15) — *planning ADR; no implementation in this PR.*

## Context

ADR 0182's CRAWL/WALK/RUN loop is live and validated: two scheduled days,
two clean autonomous merges, 100% gate-pass, self-measured by the outcome
ledger. But it is **fuel-starved** — the chimera repo is exhausted of
organic gate-visible debt (ruff clean incl. stricter rules, deprecations
cleared, ResourceWarnings non-deterministic). The real backlogs live in
*other* repos (claude-daemon: 6 issues, autoresearch-unified: 4, …), which
the loop cannot reach: the soak is chimera-self-improvement end to end
(`REPO_ROOT=$(pwd)`, gate = `chimera verify` = chimera's own ruff+pytest).

Two things are now true and shape this ADR:

1. **The work is code, not creativity.** Every CRAWL deliverable is a code
   PR; the gate is ruff+pytest; the value is correct, scoped diffs. The
   model ladders (ADR 0072 family) were built as a *diverse cross-vendor*
   spread; for a code-production agent they should be biased toward the
   best **tool-calling code models**, with a fast, validated path to ingest
   new ones as the frontier moves (Kimi 2.7 Code is the current example).
2. **Reach is the fuel constraint.** Sustainable work volume — the
   evidence base that justifies RUN-phase auto-merge — requires acting on
   repos that actually have backlogs. That is a different operating mode:
   Chimera as a *general* coding agent, not a self-improver.

This ADR plans the two coordinated pillars of that transition —
**capability** (code models) and **reach** (multi-repo) — and sequences
them evidence-first. It deliberately defers implementation; each pillar
graduates to its own build ADR.

---

## Pillar A — Code-model ingestion (smaller, safer, first)

### Why first
Better code/tool-calling models improve the loop **immediately**, even on
the self-repo, and the work is bounded and low-risk (additive config behind
the existing tier seam). And the ADR 0182 outcome ledger now *measures*
whether a model helps (gate-pass rate, cost-per-landed-change), so a model
swap becomes an evidence decision, not a guess.

### The seam (already clean)
A model is `ModelConfig` (`model_id`, rate caps, `input/output_cost_per_mtok`,
`provider`, `openrouter_model_id`) + `ModelCapabilities` (`supports_tools`,
`supports_json_mode`, `reasoning_optimized`, `context_tokens`, …), composed
as a `LadderRung` in one of `TIER_LADDERS` (`haiku`/`sonnet`/`opus`)
([chimera/providers/tiers.py](../../chimera/providers/tiers.py)). Adding a
model is a few declarative lines; OpenRouter is the transport
(`openrouter_model_id`).

### Design

1. **A code-orientation bias.** ACT's build loop (the `sonnet` ladder, the
   "operator-selected diverse spread") should be re-weighted to lead with
   tool-calling code specialists. Options to decide at build time:
   - add a `code_optimized: bool` to `ModelCapabilities` (parallel to
     `reasoning_optimized`) and have ACT's rung selection prefer it; **or**
   - introduce a dedicated **`code` tier ladder** that ACT uses by default
     for CRAWL/soak work, leaving `sonnet`/`opus` for the rare
     non-code/creative path.
   Recommendation: the `code_optimized` flag (smaller change, composes with
   the existing ladders and complexity-routing, ADR 0166).

2. **An ingestion checklist (make it a repeatable 20-minute operation):**
   - add `LADDER_<MODEL> = ModelConfig(..., openrouter_model_id="<slug>")`
     + a `LadderRung` with declared capabilities;
   - `chimera tiers --json` to sync price + confirm the slug resolves;
   - `chimera ping --provider openrouter` (or a model-scoped ping) for
     liveness;
   - an **ACT A/B soak**: run the same CRAWL spec on the incumbent vs. the
     new model and compare the ledger (gate-pass, rounds, cost). Promote
     into the ladder only on a win or parity-at-lower-cost.

3. **Kimi 2.7 Code as the worked first ingestion.** Moonshot's
   `moonshotai/kimi-*` code model (confirm the exact OpenRouter slug at
   ingestion via `chimera tiers`). Add as a `code_optimized` rung; A/B it
   against the current `sonnet` lead (deepseek-v4-pro) on the CRAWL backlog;
   promote on evidence.

> **Built (tier composition, 2026-06-15).** Per operator decision, a
> dedicated **`code` tier** now exists (`tiers.CODE_LADDER`,
> `TIER_LADDERS["code"]`): `moonshotai/kimi-k2.7-code` (added) → deepseek-v4-pro
> → z-ai/glm-5.1 → qwen/qwen3.7-max → claude-opus (trailing safety-net, ADR
> 0072). It is a **selectable** tier orthogonal to the haiku→sonnet→opus
> cost-escalation axis (`MODEL_TIERS` / `escalation._TIER_ORDER` unchanged),
> reachable via `select_rung("code")` / `CHIMERA_ACT_FORCE_MODEL`. **Still
> remaining for A.1:** verify Kimi's price/slug against the live catalog,
> the A/B soak measured by the outcome ledger, and the default-routing
> activation (point ACT at `code` for CRAWL work) — that flip stays
> evidence-gated. We chose a dedicated tier over the `code_optimized` flag
> because a 4th tier doesn't disturb the existing 3-tier escalation or the
> witness/safety-net invariants.

> **Built (A/B harness, 2026-06-15).** The A/B soak scenario now exists:
> `scripts/ab_soak.sh` runs one backlog spec through the real soak loop twice,
> pinning ACT to each model arm via `CHIMERA_ACT_FORCE_MODEL`, and scores them
> head-to-head from the `[soak-outcome]` line into the outcome ledger
> (arm-tagged run_ids). Enabling change: `CHIMERA_ACT_FORCE_MODEL` now resolves
> **any** ladder model to its real rung (true provider + cost) — previously it
> forced every id onto the Anthropic provider, so a kimi/deepseek (OpenRouter)
> arm was impossible (`chimera/core/act.py:_forced_rung`). The default arms are
> the only models that differ between the `code` and `sonnet` tiers — their
> leads: `deepseek/deepseek-v4-pro` (incumbent) vs `moonshotai/kimi-k2.7-code`
> (candidate). The probe spec lives in `mind/ab/` (outside the daily picker),
> stays red on base (never merged), so the A/B is repeatable.

> **First live run (2026-06-15) + harness fix.** Ran the probe A/B live (full
> writeup: `mind/research/ab-codetier-first-run-2026-06-15.md`). Both arms
> passed their in-loop gate and committed (deepseek $0.14, kimi $0.35). But the
> raw cost verdict was **misleading**: because each arm authors its own gate
> test (Design 2), deepseek passed by under-implementing (no `d` unit, no
> order/dedup enforcement, wrong exception type) AND under-testing in tandem.
> Graded against a canonical acceptance test, kimi scored **18/18** vs
> deepseek **13/18**. Two consequences: (1) **finding** — kimi-k2.7-code is the
> better code model on a spec'd task; its cost premium bought correctness;
> (2) **harness fix** — `ab_soak.sh` now grades each arm's produced module
> against a fixed `<spec>.accept.py` and the verdict is quality-first (cost only
> breaks a quality tie), so a cheaper-but-weaker arm can't win. **Still
> remaining for A.1:** a re-run under accept-grading on a representative task
> mix, then — on a graded kimi win worth the cost — the default-routing flip
> (point CRAWL ACT at `code`). The flip stays evidence-gated; this run is
> suggestive, not yet decision-grade across tasks.

> **Battery run (2026-06-15) — full writeup
> `mind/research/ab-codetier-battery-2026-06-15.md`.** Ran the graded A/B across
> 4 varied probes (`scripts/ab_battery.sh`: slugify/easy, duration/medium,
> roman/med-hard, intervals/hard). Result: **kimi 91/104 (88%) at $0.58 vs
> deepseek 88/104 (85%) at $0.73** — quality a statistical dead heat (probe wins
> 2–2; the +3 is within noise), but **kimi ~21% cheaper**. The decisive finding
> is *methodological*: **run-to-run variance is large** — the duration probe
> reversed winners vs the standalone run (kimi 18→12, deepseek 13→18), proving
> one trial per cell is dominated by sampling noise. **Recommendation
> (operator-gated): promote the kimi lead** — it is non-inferior on quality and
> cheaper (the less-noisy signal), with CRAWL's bounded downside (draft-PR-only,
> manual review, code-ladder fallbacks) and the daily ledger as the ongoing
> monitor. **Before any quality-based claim is treated as robust:** add an
> `AB_TRIALS` mode (n>1 per cell, compare distributions). Harness hardening
> shipped alongside: `ab_battery.sh` pins `TASK_BASE` to a SHA so a concurrent
> merge can't move the base ref mid-run (it did, once — a benign but real
> footgun).

> **Routing flip DONE (2026-06-15) — A.1 complete.** Per operator decision,
> CRAWL ACT now routes at the `code` tier by default (kimi-k2.7-code lead, with
> the deepseek→glm→qwen→opus fallback ladder). Seam: `CHIMERA_ACT_TIER`
> (`ActExecutor.from_env`, default `haiku`; an explicit caller tier still wins);
> `crawl_daily.sh` exports `CHIMERA_ACT_TIER=code`. `recommended_tier` now passes
> a non-`_TIER_ORDER` tier through unchanged (the haiku/sonnet/opus floors no
> longer rewrite `code`→`sonnet`); the `code` tier gets sonnet-equivalent token
> headroom (8192) so kimi's reasoning-then-code pattern isn't truncated. The
> daily outcome ledger is the ongoing monitor; revert is a one-line env change.
> This closes Pillar A.1 — composition, ingestion, pricing, graded A/B, and the
> evidence-gated routing flip are all done. (A.2 — fold the result into the
> standing ladder + keep the ingestion checklist — remains a follow-up.)

> **`AB_TRIALS` multi-trial mode (2026-06-15).** `ab_battery.sh` gained an
> `AB_TRIALS=N` knob: each (probe, arm) cell runs N times and the scorecard
> reports the *distribution* — mean spec-pass `[min–max]`, pooled rate, and
> mean within-cell variance — not a single noisy sample. The verdict treats a
> quality gap within ~5pp as a tie and decides on cost (the lower-variance
> signal). This is the principled answer to the battery's headline finding
> (one trial per cell can flip a winner). Trials are disambiguated via
> `AB_RUN_TAG` (threaded through `ab_soak.sh`'s run-id/worktree/ledger slug).
> Also: the code tier's per-completion OUTPUT cap was raised 8192→16384
> (`CHIMERA_ACT_MAX_TOKENS_CODE`-overridable) so larger diffs aren't truncated —
> distinct from kimi's 256K *input* context, which was never constrained.

> **N-way arena (2026-06-15) — `scripts/ab_arena.sh`; full writeup
> `mind/research/ab-arena-2026-06-15.md`.** Ran all four suggested open code
> models on all four probes (16 soaks, graded). Leaderboard:
> **qwen3.7-max 104/104 @ $0.135/run (rank 1, 3 probe-wins)**, kimi-k2.7-code
> 104/104 @ $0.190 (rank 2), glm-5.1 99/104, deepseek-v4-pro 95/104 (last,
> priciest). **Finding: qwen and kimi are co-quality-leaders (both perfect across
> all difficulty tiers — a real tie, not noise), and qwen is ~29% cheaper.** The
> current promoted lead (kimi) is co-best on quality but not the value pick. The
> grader is discriminating (deepseek 91%, glm 95%), so the perfect scores are
> credible. **Open decision:** confirm qwen's parity with a short `AB_TRIALS=3`
> qwen-vs-kimi run, then consider re-ordering the code ladder value-first
> (`qwen → kimi → glm → deepseek → opus`). Single-trial caveat applies to the
> mid-pack; the top tie is solid (both maxed). Routing change stays operator-gated.

> **Lead switched to qwen3.7-max; kimi dropped (2026-06-17).** Per operator
> decision, the code-tier lead is now **qwen3.7-max** and kimi-k2.7-code was
> removed from the ladder. Rationale: the arena tied them on quality
> (both 104/104) but qwen was ~29% cheaper, AND a guarded instrumented
> reproduction found kimi repeatedly **stalls on the single-binary `shell`
> tool protocol** (spamming `bash -c`, hitting `scope_evasion` at max_rounds
> and getting trust-demoted) — a poor fit for the soak loop despite its arena
> score. New `CODE_LADDER` (value-first): `qwen3.7-max → glm-5.2 →
> deepseek-v4-pro → claude-opus` (safety-net). Also: **`z-ai/glm-5.1` →
> `z-ai/glm-5.2`** (upstream replacement) across the sonnet + code ladders
> (pricing carried from 5.1, verify at next ingestion). Same finding-record
> as the crash post-mortem: the in-process memory profile of a single cycle
> is flat (~116MB) — the crashes were concurrency (the resurrected daily
> CRAWL running soaks alongside A/B runs), now mitigated.

### Validation
- The flag-matrix / registry tests stay green (ladders are data).
- New: a model-ingestion smoke (the new rung resolves, prices, pings) and
  the A/B soak recorded in the outcome ledger.

### Risk
- Frontier code models can be pricier — the three cost caps (ADR
  0072/0076/0079) bound it, and cost-per-landed-change in the ledger makes
  a bad trade visible.
- Quality regressions — caught by the A/B before promotion; never a blind
  swap.

---

## Pillar B — Multi-repo reach (larger, riskier, second)

### Current status (code-grounded)
Execution is ~0% multi-repo. Only **ingestion** is repo-aware
(`chimera backlog from-issues --repo <r>` records `issue: owner/repo#N`),
and the verification *primitive* (`repo_verify.verify_at_ref` /
`classify_gate_transition`) is already `repo_root`-parameterized — but every
caller passes `Path.cwd()`. Everything that *acts* (`real_task_soak.sh`,
`crawl_daily.sh`, the `BacklogSpec` model, the `chimera verify` gate) is
hardcoded to the local chimera repo.

### Design (the gated work)

1. **Spec model**: add `repo` (owner/name) and `verify_cmd` to
   `BacklogSpec` — a foreign repo's gate is its own test command
   (pytest / npm test / cargo test / …), which `chimera verify` cannot
   express. `verify_cmd` is the per-repo verify abstraction.
2. **Soak generalization** (the bulk): `real_task_soak.sh` clones/worktrees
   the *target* repo at `base`, runs *its* `verify_cmd` as the gate (with
   the same red→green gate-visibility, which `verify_at_ref` already
   supports against an arbitrary `repo_root`), and drives the agent against
   that checkout. The chimera-specific gates (`chimera verify`,
   `faithfulness`, `review`) become the default for self-repo and one
   option among per-repo verify commands.
3. **Foreign-repo agent context**: the loop currently reads chimera's
   `mind/`/`state/`; a foreign task needs a neutral/target context, not
   chimera's ontology. Define a "contextless build" mode for foreign repos.
4. **PR targeting + safety** (the real risk): open the draft PR against the
   target repo. Acting on *other people's repos* is a materially larger
   blast radius than self-improvement, so this needs:
   - an explicit **repo allowlist** (start: elementalcollision/* only);
   - **draft-PR-only**, manual-handoff (no auto-merge cross-repo, ever, in
     this phase);
   - trust-gating (≥ T-tier) and the existing scope/cost/critic gates;
   - a scope/secrets review (the agent runs foreign test suites — sandbox
     posture per ADR 0175 applies).

### Why second
It is a product-and-safety decision plus significant rework, not a bounded
increment. It should not start until Pillar A has improved completion
quality (so foreign-repo tasks have a real chance of converging) and until
the safety review above is done. Its own build ADR will carry the design in
full.

---

## Sequencing & graduation

1. **Pillar A.1** — add `code_optimized`; ingest Kimi 2.7 Code; A/B on the
   CRAWL backlog; promote on ledger evidence. *(small, immediate, measured)*
2. **Pillar A.2** — fold the A/B result into the default ACT ladder; keep
   the ingestion checklist as the standing path for the next model.
3. **Pillar B.0** — a multi-repo *build* ADR: verify abstraction, soak
   generalization, foreign-repo context, repo allowlist, safety review.
4. **Pillar B.1+** — implement against one allowlisted repo with the
   richest backlog (claude-daemon), draft-PR-only, evidence into the same
   ledger.

Auto-merge (RUN) remains gated on the ledger across both pillars; nothing
here flips it on.

## Falsification / revisit triggers

- If the Kimi (or any) code-model A/B shows no gate-pass/cost win over the
  incumbent, don't promote it — the ladder is evidence-curated, not
  fashion-driven.
- If multi-repo's per-repo `verify_cmd` proves too fragile across repos
  (flaky foreign suites, environment drift), narrow to repos with
  containerised/deterministic CI before broadening.
- If acting on foreign repos surfaces any safety/scope incident, halt
  Pillar B and treat it as a gate-hardening event (per the ADR 0182
  incident discipline).
