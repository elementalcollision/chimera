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

**Filled by operator after step 4.** Paste the output of
`format_summary_table(summarize_results(...))` here.

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| single-session-user | _TBD_ | _TBD_ | _TBD_ |
| single-session-assistant | _TBD_ | _TBD_ | _TBD_ |
| multi-session | _TBD_ | _TBD_ | _TBD_ |
| knowledge-update | _TBD_ | _TBD_ | _TBD_ |
| temporal-reasoning | _TBD_ | _TBD_ | _TBD_ |
| abstention | _TBD_ | _TBD_ | _TBD_ |
| | | | |
| **overall** | _TBD_ | _TBD_ | _TBD_ |

## Sweep metadata

**Filled by operator.**

- Date of sweep: _YYYY-MM-DD_
- Upstream LongMemEval commit / tag: _e.g. `v0.3.1` or `git rev-parse HEAD`_
- Chimera commit: _e.g. `git rev-parse HEAD`_
- Judge model: _e.g. `gpt-4o-2024-08-06` / `claude-sonnet-4-5`_
- Total wall-clock time: _e.g. ~12m_
- Total inference cost (Chimera-side): _e.g. $0 — adapter returns prompts, not answers_
- Total inference cost (judge side): _e.g. ~$8 across 500 items_
- Notable failures / skipped items: _free text_

## Promotion checklist (ADR 0135 → Accepted)

- [ ] Baseline scores table above is filled in (not `_TBD_`).
- [ ] Sweep metadata is filled in.
- [ ] [docs/adr/0135-longmemeval-integration.md](../../docs/adr/0135-longmemeval-integration.md) status changed `Proposed` → `Accepted` with the baseline-capture date.
- [ ] [docs/adr/README.md](../../docs/adr/README.md) row updated to `Accepted`.
- [ ] PR opened that contains this filled-in note + the two ADR edits.

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
