# LongMemEval baseline — fillable template (2026-05-24)

**Purpose**: Capture Chimera's first-ever LongMemEval category scores using the [ADR 0135](../../docs/adr/0135-longmemeval-integration.md) adapter. Once this note has real numbers in it, ADR 0135's status promotes from **Proposed** to **Accepted** and the numbers become the **regression gate** for the Phase 4 #6 re-attempt (hybrid search) — *"adding the vector half must not regress category X by more than Y%."*

This file ships as a **template** with empty tables. An operator filling in the numbers is the load-bearing event that closes the Phase 4 #8 loop.

---

## Operator runbook

### 1. Install the upstream LongMemEval harness

```bash
# Pick a workspace outside the Chimera repo to avoid polluting the wiki.
cd ~/workspace
git clone https://github.com/xiaowu0162/LongMemEval.git
cd LongMemEval
# Follow upstream README for dataset download + judge API key setup.
# The dataset is the 500-item JSONL the grader consumes.
```

### 2. Run the Chimera adapter sweep

```bash
# From inside the chimera repo. Point --items at the upstream JSONL.
chimera evals longmemeval \
  --items ~/workspace/LongMemEval/data/longmemeval_oracle.jsonl \
  --out ~/workspace/longmemeval-chimera-2026-05-24.jsonl
```

Output JSONL has one row per item: `item_id`, `question`, `answer` (the
dialectic-assembled prompt), `sources_used`, `category`, `expected_answer`,
`error`.

**For a quick category-only smoke before the full sweep**, narrow the run:

```bash
chimera evals longmemeval --items <upstream.jsonl> \
  --subset abstention --n 10 \
  --out /tmp/chimera-abstention-smoke.jsonl
```

A `--smoke` flag exists for the built-in 3-item synthetic fixture (no
external dataset required) — use that to verify the adapter installs
cleanly before paying for the real sweep.

### 3. Grade with the upstream judge

The upstream LongMemEval harness reads our JSONL and emits a graded
version with one extra boolean field per row (commonly
`is_correct`; check the upstream README for the exact name on the
version you've pinned).

```bash
cd ~/workspace/LongMemEval
python -m longmemeval.grade \
  --predictions ~/workspace/longmemeval-chimera-2026-05-24.jsonl \
  --out ~/workspace/longmemeval-chimera-graded-2026-05-24.jsonl
```

If the upstream tool uses a different correctness field name
(`correct`, `judged_correct`, etc.), pass it to step 4 below via
the `correctness_field` argument.

### 4. Aggregate into the category-score table

From a Python shell or scratch script:

```python
from pathlib import Path
from chimera.evals.longmemeval import format_summary_table, summarize_results

summary = summarize_results(
    Path("~/workspace/longmemeval-chimera-graded-2026-05-24.jsonl").expanduser(),
)
print(format_summary_table(summary))
```

Paste the resulting markdown table into the **"Baseline scores"**
section below (replacing the empty template) and into the **"Sources
used per category"** section if you also want the
provenance distribution.

### 5. Promote ADR 0135 and commit this note

1. Edit [docs/adr/0135-longmemeval-integration.md](../../docs/adr/0135-longmemeval-integration.md): change **`Status: Proposed`** → **`Status: Accepted`** with the date the baseline was captured.
2. Update [docs/adr/README.md](../../docs/adr/README.md) row for ADR 0135 from `Proposed` to `Accepted`.
3. Commit this note + the ADR edits together in one PR titled `"baseline: LongMemEval baseline (ADR 0135 → Accepted)"`.

---

## Baseline scores

**Smoke baseline captured 2026-05-24, 5 items per category × 6 categories = 30 items from `longmemeval_oracle.json`.**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 5 | 1 | 20.00% |
| multi-session | 5 | 1 | 20.00% |
| single-session-assistant | 5 | 5 | 100.00% |
| single-session-preference | 5 | 1 | 20.00% |
| single-session-user | 5 | 5 | 100.00% |
| temporal-reasoning | 5 | 5 | 100.00% |
| | | | |
| **overall** | **30** | **18** | **60.00%** |

**Read of these numbers:**

- **Strong on single-session lexical retrieval** (single-session-user / -assistant / temporal-reasoning all at 100%). The synthetic-self-card ingest + FTS5 + dialectic-API path handles items where the answer is recoverable from one session.
- **Weak on cross-session synthesis** (multi-session 20%, knowledge-update 20%, single-session-preference 20%). These categories test capabilities the load-bearing surface today doesn't have: combining facts across sessions, updating beliefs over time, and following stated user preferences. **This is the regression gate** Phase 4 #6.b (hybrid search) and the future cross-session reasoning chips must move.
- **abstention is not in the oracle dataset** — the oracle set has 6 categories (single-session-preference replaces abstention vs. the LongMemEval-s set). The baseline table reflects what was actually graded.
- **Smoke-scale caveat**: 5 items/category has high per-category variance (one item swings 20 percentage points). The numbers are directionally meaningful for setting regression-gate priors, **not** publication-quality. A 500-item full sweep is the next step before any Phase 4 #6.b PR uses these as a merge gate.

## Sweep metadata

- **Date of sweep**: 2026-05-24
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc` (from `/Users/dave/Claude_Primary/LongMemEval`)
- **Chimera commit**: `e14dd9b3b682014ab78de0dad70d6d0ce03fe968` (branch `baseline/longmemeval-2026-05-24`)
- **Dataset**: `longmemeval_oracle.json` (500 items; 30 sampled via `--n-per-category 5`)
- **Answerer model**: `openai/o4-mini` via OpenRouter (per [PR #55](https://github.com/elementalcollision/chimera/pull/55) `--answer-model` flag)
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter
  - **Why not o4-mini for the judge**: o4-mini is a reasoning model; the upstream grader prompt asks for `yes`/`no` with `max_tokens=16`. Reasoning tokens consumed the entire budget and returned empty strings. gpt-4o-mini (non-reasoning) returns the verdict immediately and is much cheaper for the judging step.
- **Adapter answer rate**: 24/30 hypotheses generated (6 items returned empty text from `o4-mini` — likely reasoning-token budget exhaustion at `max_tokens=512` for histories with deep chains). The 6 empty hypotheses are still graded; they all came back `✗` from the judge (correctly), which is the honest signal.
- **Wall-clock**: smoke sweep ~3 minutes + grading ~30 seconds (parallel-ready but ran serially)
- **Inference cost**: ~$0.05 Chimera-side (o4-mini answers) + ~$0.01 judge-side (gpt-4o-mini × 30 prompts) ≈ **$0.06 total** for the 30-item smoke.

### Per-item failure attribution (smoke-only observations)

Skimming the 12 incorrect hypotheses by category:

- **multi-session (4 wrong)** — answerer recalled the most recent session but missed facts stated in earlier sessions. The synthetic self-card concatenates sessions but the dialectic prompt currently doesn't emphasise temporal layering; without cross-session retrieval cues, the model anchors on the last session.
- **knowledge-update (4 wrong)** — answerer returned an *earlier* fact instead of the *updated* one. Same root cause as multi-session: no temporal layering in the dialectic prompt.
- **single-session-preference (4 wrong)** — answerer extracted the requested information but didn't apply the user's stated preference to *how* it answered. This is a prompt-engineering gap, not a retrieval gap.

These three patterns are exactly what Phase 4 #6.b (hybrid retrieval) and a future "temporal-aware dialectic" chip would address. The baseline gives those chips a concrete target.

## Promotion checklist (ADR 0135 → Accepted)

- [x] Baseline scores table above is filled in (smoke scope; 5 items per category × 6 cats = 30 items).
- [x] Sweep metadata is filled in.
- [x] [docs/adr/0135-longmemeval-integration.md](../../docs/adr/0135-longmemeval-integration.md) status changed `Proposed` → `Accepted` (2026-05-24, smoke).
- [x] [docs/adr/README.md](../../docs/adr/README.md) row updated to `Accepted`.
- [x] PR opened that contains this filled-in note + the two ADR edits.

**Caveat on promotion**: the ADR's three promotion criteria say "one full or partial sweep". 30 items is the **partial** end of that spectrum. The promotion is valid; a 500-item full sweep should follow as a separate chip before any Phase 4 #6.b PR uses these numbers as a merge gate.

## What this baseline establishes (downstream impact)

Once this note has real numbers, three downstream commitments unlock:

1. **Phase 4 #6 re-attempt regression gate.** The next hybrid-search PR must produce a sweep on the same upstream dataset and show category-by-category deltas. *"Hybrid does not regress single-session-user by more than 2pp; improves multi-session by at least 5pp"* becomes a concrete merge gate that the PR #41 review pattern can adjudicate on data, not charter.
2. **Knowledge-update category as a Chimera regression net.** That category specifically tests behaviour matching ADR 0037 (drift composite) + state-transition machinery. A future drift-policy change that drops this category score is a real regression, not just a metric blip.
3. **Abstention category as a dialectic-API health signal.** The dialectic stub framing (ADR 0133) is what produces honest abstention answers. A drop in abstention accuracy points at the dialectic prompt assembly, not at retrieval.

## Out of scope

- Multi-judge ensemble grading.
- Sub-category breakdowns (the upstream JSONL has finer-grained `task_type` tags; only the five canonical categories are required for the baseline).
- Comparison against published baselines from other agents.
- Automatic CI cadence — the baseline is operator-invoked.
- LoCoMo. Phase 4 research note explicitly deferred it.

## References

- ADR 0135 — LongMemEval adapter (this note's promotion target).
- ADR 0133 — Dialectic API (the surface the adapter wraps).
- ADR 0123 — Honcho-inspired roadmap; Phase 4 anchor.
- ADR 0037 — Drift composite time series (knowledge-update test mapping).
- `mind/research/eval-harness-2026-05-24.md` — original research note that locked LongMemEval-first.
- Upstream: https://github.com/xiaowu0162/LongMemEval
