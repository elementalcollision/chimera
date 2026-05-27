# Changelog

All notable releases of Chimera are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/) with the v4.0 stability contract recorded in
[ADR 0025](docs/adr/0025-v4-stability.md).

Earlier releases (v1.0 → v4.113.0) are documented through the ADR series and
git tags; this changelog is introduced at v4.114.0 as the load-bearing
public record for releases going forward.

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
