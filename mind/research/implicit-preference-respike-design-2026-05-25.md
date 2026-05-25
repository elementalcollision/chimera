# Implicit-preference respike — redesigned heuristic (2026-05-25)

**Companion to**: [ADR 0138](../../docs/adr/0138-implicit-preference-inference.md)
**Predecessors**: PR #72 (initial heuristic, reverted by PR #74), PR #73 (spike result)
**This chip**: PR (this branch) — redesigned heuristic + tests + ADR amend; **no respike run**

## Why a redesign, not Option C

PR #73's spike landed three Gate A flips (`0a34ad58` Tokyo-anxiety,
`6b7dfb22` painting-block, `95228167` music-store). These items
share a shape: the user's prior turns contained a clearly-stated
preference or constraint that the gold answer required the model to
transfer to a tangentially-related new question. The intervention
worked on those — surfacing the signal in a `## User context` block
above the verbatim transcript pulled the answerer's attention onto
relevant context before it skimmed `## History`.

The intervention also broke five right items (Gate B). Diagnostic on
the five regressions points at content noise, not at structural
overreach:

- `1c0ddc50` (commute): user said both "I love history podcasts" AND
  "I'm not into true crime anymore"; only the affirmative match
  surfaced because the heuristic had no negation pattern.
- `32260d93` (show/movie): the section bloated with `I'm wondering`,
  `my question`, and other filler — drowning out the actual
  comedy-storytelling preference deeper in the transcript.

So the redesign keeps the structural intervention (the `## User
context` section above `## History`) and rebuilds the content filter.

## Redesigned heuristic

### Patterns kept and refined

| Class | Pattern | Rationale |
|---|---|---|
| Preference verbs | `\bI\s+(?:prefer\|like\|love\|hate\|avoid\|tried\|use\|own\|bought)\b` | Clear taste/ownership/habit verbs. PR #72 included `have/usually/recently` — dropped here because `I have a question` / `I usually wonder` are filler. |
| Negation/rejection | `\b(?:don't\|won't\|wouldn't\|never)\s+(?:like\|prefer\|enjoy\|want\|do)\b` | New. PR #73's `1c0ddc50` regression showed this gap directly. |
| Not-X phrases | `\bnot\s+(?:interested in\|a fan of\|into)\b` | New. Captures softer rejection. |
| Identity statements | `\b(?:I'?m\|I\s+am)\s+(?:a\|an)\s+\w+\b` | New, narrower than bare `I'm`. Matches "I'm a vegetarian", "I am an engineer"; rejects "I'm wondering", "I am here". |

### Patterns dropped

| Old pattern | Why dropped |
|---|---|
| `\bI\s+(am\|'m)\b` (bare) | Matches "I'm wondering" / "I am here" — pure filler. |
| `\bmy\s+\w+\b` | Matches "my apologies" / "my question" — pure filler. |
| First-user-turn anchor (unconditional) | PR #73 evidence: incidental first turns (e.g. "Planning a Seattle trip") were captured even when irrelevant to the question. |

### Scope restriction

Only the **last 5 non-empty user turns** are considered. PR #73's
diagnostic on `1c0ddc50` showed the heuristic surfacing both an early
preference and a later rejection without recency awareness; the
cap-at-6 limit prevented total bloat but didn't eliminate stale-vs-recent
conflicts. Last-5 prefers the user's current state.

### Bounds preserved

- Cap at 6 bullets
- Truncate each bullet to 200 chars
- Dedup on exact-match snippet
- Empty list → omit the section entirely (no `## User context` header)

## Section placement (unchanged from PR #72)

Between `**Today's date:**` and `## History`. The prominence shape
that produced the 3 Gate A flips is preserved.

## Files in this chip

| File | Change |
|---|---|
| `chimera/evals/longmemeval.py` | Rebuilt `_extract_user_context` helper + integration point in `ingest_history` |
| `tests/test_longmemeval.py` | 5 new tests (filler rejection, negation, recency, identity vs filler, no-signal omission) |
| `docs/adr/0138-implicit-preference-inference.md` | Amended with "Redesigned heuristic" subsection; Status stays **Proposed** |
| `mind/research/implicit-preference-respike-design-2026-05-25.md` | This note |

## Respike runbook (operator-fired post-merge)

Identical protocol to PR #73's spike — reuse the same n=30 SPP subset
so paired-item comparison stays clean against the same PR #70 baseline:

```bash
mkdir -p /tmp/chimera-baseline-t2b-v2
# Reuse the filtered SPP dataset from PR #73's spike.
cp /tmp/chimera-baseline-t2b/spp-only.json /tmp/chimera-baseline-t2b-v2/spp-only.json

uv run chimera evals longmemeval \
    --items /tmp/chimera-baseline-t2b-v2/spp-only.json \
    --answer --answer-model openai/o4-mini --answer-max-tokens 2048 \
    --out /tmp/chimera-baseline-t2b-v2/respike.jsonl

uv run python /tmp/chimera-baseline/grade.py \
    /tmp/chimera-baseline-t2b-v2/respike.jsonl \
    /tmp/chimera-baseline-t2b-v2/spp-only.json \
    /tmp/chimera-baseline-t2b-v2/respike.graded.jsonl \
    openai/gpt-4o-mini
```

PR #73's paired-item analysis script can be reused with input paths
swapped. Expected cost ≈ $0.05; expected runtime ≈ 5 min.

## Pre-registered gates

| Gate | Threshold | Status if breached |
|---|---|---|
| **Gate A** | ≥2/16 wrong→right | Required signal. Falsifies prominence-shape direction if missing. |
| **Gate B** | 0/14 right→wrong | **Load-bearing**. PR #72 failed here. |
| **Regression check** (supplementary) | The 3 PR #73 wrong→right flips (`0a34ad58`, `6b7dfb22`, `95228167`) should still flip | If any reverts to right→wrong, the redesign is over-narrow on the items where the intervention demonstrably helps. |

## Decision tree on respike outcome

| Outcome | Action |
|---|---|
| Both gates pass + regression check passes | Charter T1.6 full sweep; flip ADR 0138 to **Accepted** on promotion. |
| Gate A passes, Gate B fails | Prominence-shape direction confirmed, no heuristic sharp enough → **Option C** (hybrid retrieval / ingestion-time preference extraction in a separate chip). |
| Gate A fails | Prominence-shape direction wrong → **Option C**. |
| Both gates pass, regression check fails on 1 item | Honest disclosure; ship if the new gains exceed the lost flip on net. |

## Honest disclosures

- The redesign is informed by but not validated against the 5 Gate B
  regressions. The respike is the validation step.
- Restricting scope to last-5 user turns trades off coverage:
  preferences stated only once in early sessions will be dropped.
  PR #73's evidence suggests early-only preferences are rare among the
  16 wrong items; this is a calibrated trade.
- The respike reuses PR #73's filtered SPP dataset and the same
  o4-mini answer model / gpt-4o-mini grader. Methodology drift risk
  is low.
- n=30 is small; both gates remain noise-floor-aware (PR #73
  established Gate B as significant at p≈0.005 under the null).
