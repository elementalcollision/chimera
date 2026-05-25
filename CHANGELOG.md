# Changelog

All notable releases of Chimera are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/) with the v4.0 stability contract recorded in
[ADR 0025](docs/adr/0025-v4-stability.md).

Earlier releases (v1.0 → v4.113.0) are documented through the ADR series and
git tags; this changelog is introduced at v4.114.0 as the load-bearing
public record for releases going forward.

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
