# Implicit-preference spike — design + operator runbook (2026-05-25)

**Purpose**: Phase-1 design note for the ADR 0138 single-category
n=30 spike. Companion to
[`implicit-preference-inference-2026-05-25.md`](./implicit-preference-inference-2026-05-25.md)
(the diagnostic) and
[ADR 0138](../../docs/adr/0138-implicit-preference-inference.md)
(the locked-design decision record).

This note captures the heuristic-design justification, the
paired-item comparison protocol, and the gate verdict template the
operator fills in after running the spike. **No spike results are
included here yet** — those land in a sibling
`implicit-preference-spike-result-2026-05-25.md` once the operator
runs the runbook.

## Shape choice — Shape A (dedicated `## User context` section)

The chip charter offered three intervention shapes:

| Shape | Description | Picked? |
|---|---|---|
| A | New `## User context` section in peer card, above `## History` | ✓ |
| B | Per-turn preference highlighting inside `## History` | — |
| C | Both | — |

**Why Shape A:** Direct structural analogue of PR #69's win (the
`**Today's date:**` anchor above `## History`). The diagnostic
[Test 2](./implicit-preference-inference-2026-05-25.md#test-2--right-items-already-do-the-inference)
showed the model engages with grounding when it sits at the top of
the card; the failure mode is the answerer skimming past
preferences buried in a long transcript. Shape A surfaces the same
signal in a checklist-shaped block the answerer is more likely to
honor. Shape B would require the heuristic to fire inside the
session body (more disruptive; harder to roll back). Shape C adds
visual noise that could hurt other categories with no mechanism
gain over A.

## Heuristic justification

The verb set
(`have|own|like|prefer|use|bought|usually|recently|tried|don't like|hate|love|avoid|am|'m`)
was chosen by reading the 14 right items + 16 wrong items in
`longmemeval_oracle.json` and tallying the verbs that appear in
preference-bearing turns. The pattern covers:

| Failure class (from diagnostic) | Verb-set coverage |
|---|---|
| P-HEDGE (7) | `own` (power bank), `like` (mid-century modern), `bought` (utensil holder), `am` (researcher), `'m` (language learner) |
| P-GENERIC (6) | `tried` (lemon-poppyseed cake), `prefer` (Strat vs Les Paul), `use` (Suica), `bought` (creamer ingredients) |
| P-WRONG-TOPIC (1) | `tried` (turbinado sugar success — would land in the bullet list, but doesn't fix attention-miss) |

The `my <noun>` pattern catches ownership phrasing the verb set
misses ("my Suica card", "my cat Luna", "my deep-clean session").

**Known false-positive risk**: turns like "I am wondering about X"
or "I tried to figure out X" match the verb pattern but carry no
preference signal. The cap-at-6 rule limits how much noise can
land. The result note must disclose whether false positives
appeared in the 30 items.

**Known false-negative risk**: deeply paraphrased preferences ("the
last cake I made was lemon-poppyseed" — no first-person verb) won't
match. The first-user-turn-as-anchor rule provides a fallback
topic-frame even when no preference verb appears.

## Paired-item comparison protocol

Pre-intervention data: `/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl`
(PR #70's 500-item sweep, `main` at `14192658`).

Post-intervention data (after operator runs spike):
`/tmp/chimera-baseline-t2b/spp-spike.graded.jsonl` (30 items).

Comparison script template (operator fills in & runs after spike):

```python
# scripts/spike-compare.py  (operator-local; not checked in)
import json
from collections import Counter

def load(p):
    with open(p) as f:
        return {
            (j := json.loads(line)).get("question_id") or j["item_id"]: j
            for line in f if line.strip()
        }

pre = {k: v for k, v in load("/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl").items()
       if v.get("category") == "single-session-preference"}
post = load("/tmp/chimera-baseline-t2b/spp-spike.graded.jsonl")

flips = Counter()
detail = []
for qid, pre_row in pre.items():
    post_row = post.get(qid)
    if not post_row:
        continue
    pre_c = bool(pre_row.get("is_correct"))
    post_c = bool(post_row.get("is_correct"))
    key = f"{'right' if pre_c else 'wrong'}->{'right' if post_c else 'wrong'}"
    flips[key] += 1
    if pre_c != post_c:
        detail.append((qid, key, pre_row.get("hypothesis","")[:60], post_row.get("hypothesis","")[:60]))

print("Pair distribution:", dict(flips))
print(f"Gate A (>=2 wrong->right): {'PASS' if flips['wrong->right'] >= 2 else 'FAIL'}")
print(f"Gate B (0 right->wrong):  {'PASS' if flips['right->wrong'] == 0 else 'FAIL'}")
for row in detail:
    print(row)
```

Outputs feed directly into the result-note template below.

## Result-note template

The operator copies this skeleton into
`mind/research/implicit-preference-spike-result-2026-05-25.md` after
running the spike:

```markdown
# Implicit-preference spike — result (2026-05-26)

**Spike date**: <YYYY-MM-DD>
**Chip branch**: chip/implicit-preference-adapter-spike-2026-05-25
**n**: 30 (single-session-preference oracle subset)
**Cost**: ~$0.05

## Pair distribution

| Pre → Post | Count |
|---|---:|
| wrong → right | <N> |
| right → wrong | <N> |
| wrong → wrong | <N> |
| right → right | <N> |

## Per-item flips

| item_id | Pre | Post | Hypothesis (pre, 60c) | Hypothesis (post, 60c) |
|---|---|---|---|---|
| ... | wrong | right | ... | ... |

## Gate verdict

- **Gate A** (≥2/16 wrong→right): PASS / FAIL
- **Gate B** (0/14 right→wrong): PASS / FAIL

## Recommendation

- BOTH gates clear → charter T1.6 full-sweep chip
- A passes, B fails → redesign heuristic (narrower preference detection); spike again
- A fails → fall back to Option C (ADR 0138 §"Options considered"); accept 46.67% floor
```

## Sample-size caveat (pre-registered)

n=16 wrong items means Gate A's ≥2-flip threshold = 12.5% flip
rate. The binomial 95% CI on 2/16 is roughly 1.6%–37%, so a 2-flip
result is statistically indistinguishable from a 1-flip or 3-flip
result. The per-item flip pattern (which specific items moved)
matters as much as the count, which is why the paired-item table
is load-bearing and not aggregate accuracy alone.

If Gate A clears by exactly 2 items, the chip charter says to
promote (per ADR 0138 §"Charter-discipline notes #4") but to flag
the result as near the noise floor in the recommendation.

## References

- [ADR 0138 — Implicit Preference Inference](../../docs/adr/0138-implicit-preference-inference.md) — the decision record.
- [`implicit-preference-inference-2026-05-25.md`](./implicit-preference-inference-2026-05-25.md) — diagnostic + per-item table.
- [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) — baseline this spike compares against.
- [PR #69](https://github.com/elementalcollision/chimera/pull/69) — structural template.
- [PR #70](https://github.com/elementalcollision/chimera/pull/70) — pre-intervention sweep.
