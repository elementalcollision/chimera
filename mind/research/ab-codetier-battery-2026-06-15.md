# Code-model A/B — varied-difficulty battery (2026-06-15)

**Scenario:** `scripts/ab_battery.sh` over 4 probes, each a graded A/B
(`ab_soak.sh`, both arms graded against a reference-validated `*.accept.py`).
Arms: `deepseek/deepseek-v4-pro` (sonnet lead, incumbent) vs
`moonshotai/kimi-k2.7-code` (code-tier lead). ADR 0183 A.1.

## Scorecard

| probe | difficulty | deepseek spec-pass | kimi spec-pass | per-probe winner |
|---|---|---|---|---|
| slugify | easy | 0/16 ($0.1904) | 9/16 ($0.2901) | kimi |
| duration | medium | 18/18 ($0.2710) | 12/18 ($0.0770) | deepseek |
| roman | med-hard | 53/53 ($0.1821) | 53/53 ($0.0384) | kimi (tie→cost) |
| intervals | hard | 17/17 ($0.0858) | 17/17 ($0.1718) | deepseek (tie→cost) |

**Totals:** deepseek **88/104 (85%)**, $0.7293, 2 wins ·
kimi **91/104 (88%)**, $0.5773, 2 wins.

Every arm passed its in-loop gate and committed (8/8). All grades were
independently re-verified against the worktrees.

## Findings

1. **Statistical dead heat on quality; kimi clearly cheaper.** kimi leads
   by +3/104 cases — almost entirely slugify (+9) minus duration (−6), i.e.
   noise-level. Probe wins are 2–2. The robust signal is cost: kimi did the
   battery for **~21% less** ($0.58 vs $0.73), and was dramatically cheaper on
   the two algorithmic probes (roman $0.04 vs $0.18; both perfect).

2. **Run-to-run variance is large — a single A/B is NOT decision-grade.**
   The `duration` probe **reversed** vs the standalone first run: kimi 18/18→
   12/18, deepseek 13/18→18/18. Same task, same models, opposite winner. Code
   generation is stochastic; one trial per (model, probe) is dominated by
   sampling noise. The 4-probe battery is still n=1 per cell — its per-cell
   verdicts inherit that noise; only the aggregate (and cost) is meaningful,
   and even the aggregate quality edge is within noise.

3. **Hard, crisply-specified tasks were solved cleanly by BOTH** (roman 53/53,
   intervals 17/17). Divergence happened on the "easy/medium" tasks where the
   spec left interpretation room (slugify's signature, duration's validation).
   Counter-intuitively, ambiguity — not algorithmic difficulty — drove the gap.

4. **The accept-grader keeps catching Design-2 gaming.** deepseek's slugify
   scored 0/16 because it reused an internal helper
   (`chimera.proposals.charter_materialize.slugify(text, *, fallback)`) with an
   incompatible signature + 48-char truncation instead of the spec's
   `slugify(text)`; its self-authored gate passed by calling with `fallback=`.
   The canonical test caught the signature divergence the in-loop gate could
   not. (A DRY instinct, but a spec violation.)

## Decision

- **Quality: parity** (within noise). **Cost: kimi wins (~21% cheaper).**
- **Recommendation (operator-gated): promote the code tier's kimi lead for
  CRAWL ACT routing.** Rationale: kimi is *non-inferior* on quality and
  *cheaper*, the cost signal is the less-noisy one, and CRAWL's downside is
  bounded (draft-PR-only, manual review, and the code ladder still falls back
  to deepseek→glm→qwen→opus). The daily outcome ledger then accumulates
  real-task evidence to confirm or refute over time.
- **Caveat / before treating any quality claim as robust:** the variance
  demands **n>1 trials per cell**. `ab_battery.sh` should grow an `AB_TRIALS`
  mode (repeat each cell k times, compare distributions) before a quality-based
  (as opposed to cost-based) decision.

## Operational notes

- **Self-inflicted bug:** merging PR #316 into `main` *mid-battery* moved the
  base ref, so the slugify-arm-A worktree (branched from the old main) saw the
  new `scripts/ab_battery.sh` as a phantom delta and its phase-2 sentinel
  spun to the wall ceiling. Harmless to results (commit + gate already done),
  but it wasted ~10 min and is a real footgun. **Fix:** pin `TASK_BASE` to a
  resolved SHA at battery start (implemented). And: don't merge to `main`
  while a battery is in flight.
- Wall: ~3h6m for 8 arms (inflated by the spin above + generous 40-min ceilings;
  real convergence was ~10–20 min/arm). All manual-handoff; nothing merged.
