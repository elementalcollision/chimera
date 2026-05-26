# LoCoMo benchmark integration — locked design

**Status**: locked
**Date**: 2026-05-26
**Chip**: net-new (LoCoMo as Chimera's second eval surface)
**Successor of**: ADR 0135 (LongMemEval integration), ADR 0142 (hybrid retrieval)
**Companion**: ADR 0144 (will land Accepted iff directional spike clears sanity rule)

## Why a second benchmark

Every reliability artifact built over the past week — ADR 0136 grounding,
ADR 0140 stratified spike protocol, ADR 0142 `_s`-only retrieval verdict,
ADR 0143 oracle noise envelope, T2.1d falsified deterministic-answerer
pivot — is conditioned on a **single** benchmark, LongMemEval. We
cannot distinguish "Chimera-the-dialectic is robust" from
"Chimera-overfits-to-LongMemEval-shape" with one corpus. A second
surface with a meaningfully different conversational shape (two-speaker
peer-to-peer simulated weeks vs LongMemEval's user-and-assistant
single-actor dialogue) gives us the triangulation point.

The chip's job is to **stand up the second surface and produce its
first baseline**, not to chase accuracy. Deliverable is infrastructure
+ a directional number.

## Corpus shape (snap-research/locomo, `data/locomo10.json`)

| Thing | Value |
|---|---|
| Source | https://github.com/snap-research/locomo |
| Paper | Maharana et al., ACL 2024 ([arXiv 2402.17753](https://arxiv.org/abs/2402.17753)) |
| License | NOASSERTION (per GitHub API) — research/eval use only; not redistributed |
| Conversations | 10 (sample_ids: conv-26, 30, 41-44, 47-50) |
| Sessions / conv | 19–32 (median ~28) |
| QA pairs / conv | 105–260 (total 1,986) |
| Speakers | Two-person peer-to-peer; named pairs (e.g. Caroline/Melanie) |
| Download | Raw fetch from `raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json` (~2.7 MB) |
| HF mirror | None published as of 2026-05-26 |

### Per-conversation schema

```
{
  "sample_id": "conv-26",
  "conversation": {
    "speaker_a": "Caroline",
    "speaker_b": "Melanie",
    "session_1_date_time": "...",
    "session_1": [
       {"speaker": "Caroline", "dia_id": "D1:1", "text": "Hey Mel!..."},
       ...
    ],
    "session_2_date_time": "...",
    "session_2": [...],
    ...
  },
  "event_summary": {...},     # annotated
  "observation": {...},       # generated
  "session_summary": {...},   # generated
  "qa": [
     {"question": "When did Caroline go to the LGBTQ support group?",
      "answer": "7 May 2023",
      "evidence": ["D1:3"],
      "category": 2}
  ]
}
```

### Question categories (numeric in the upstream JSON; canonicalised string in our adapter)

| Cat # | Upstream name (paper) | Adapter label |
|---:|---|---|
| 1 | single-hop | `single-hop` |
| 2 | multi-hop | `multi-hop` |
| 3 | temporal | `temporal-reasoning` |
| 4 | open-domain / commonsense | `open-domain` |
| 5 | adversarial (unanswerable) | `adversarial` |

Counts across the 10 conversations:

| Cat | Total |
|---:|---:|
| 1 | 282 |
| 2 | 321 |
| 3 | 96 |
| 4 | 841 |
| 5 | 446 |
| **total** | **1,986** |

Upstream uses cat-1/2/3 with the same `QA_PROMPT` ("short answer"),
cat-5 with `QA_PROMPT_CAT_5` (no "from context" restriction; the
correct answer is "I don't know"), cat-4 with the same as 1-3. Our
adapter maps this 1:1.

## Adapter design (mirrors `chimera/evals/longmemeval.py` 1:1)

### Schema

```python
@dataclass(frozen=True)
class LoCoMoItem:
    item_id: str               # f"{sample_id}::qa{idx}"
    question: str
    answer: str                # gold (may be int — coerce to str)
    category: str              # canonical label, not the int
    category_int: int          # 1..5 (kept for upstream parity)
    evidence: list[str]        # ["D1:3", ...] — provenance, not graded
    sessions: list[list[dict]] # [[{role, speaker, content}, ...], ...]
    session_dates: list[str]
    speaker_a: str
    speaker_b: str
    sample_id: str             # parent conversation id
    extra: dict
```

### Key shape decisions

1. **One LoCoMo `sample_id` produces many `LoCoMoItem`s** — one per QA.
   The conversation history is **identical** across all QAs in a sample.
   The adapter detects this via `sample_id` and **caches ingest** to
   avoid re-writing identical session markdown 100+ times. This is the
   biggest delta from LongMemEval (whose history is per-item).

2. **Role mapping**: LongMemEval has clear `user`/`assistant`; LoCoMo
   is peer-to-peer. We map `speaker_a → "user"` and `speaker_b →
   "assistant"` purely so the existing dialectic prompt machinery
   ingests cleanly. The synthetic `peers/self.md` card prepends a
   header documenting the real speaker names so the answerer can refer
   to them by name in the answer (the grader expects this — gold
   answers often contain proper names).

3. **Top-of-card "Today" anchor**: like LongMemEval post-T1.5 (ADR
   0136), we surface the latest `session_<N>_date_time` as the "today"
   anchor at top of the self-card. Temporal-reasoning items (cat 3)
   need this for "how many days ago" arithmetic.

4. **Hybrid retrieval wired from day one, default off**: LoCoMo
   conversations are 19–32 sessions, well above the default top-k=8.
   Unlike LongMemEval where `_s` was the only path needing retrieval,
   on LoCoMo **every** item is above the threshold. We expose the same
   `--hybrid-retrieval` + `--retrieval-top-k` flags as LongMemEval; the
   default-off behavior preserves the "full-context, like upstream"
   baseline.

### Ingest

`ingest_history(item)` writes a synthetic self-card (load-bearing —
the dialectic API reads this) and per-session markdown for future
FTS5/vector retrieval. Same two-surface pattern as LongMemEval. With
`hybrid_retrieval=True`, only the top-k sessions land in the self-card;
all sessions still land in the scratch dir.

### Answer

Same as LongMemEval: assemble dialectic prompt via
`gather_dialectic_context("self", mind_dir=…)`, optionally pipe through
an `AnswerFn` (OpenRouter wrapper from `chimera/cli.py`).

### Reset

Truncate the scratch dir + remove `peers/self.md`. **Skipped when
`sample_id` matches the previous item's** — sibling QAs share history.

## Grader design (`scripts/grade_locomo.py`)

Copy + adapt `grade_longmemeval.py`, keeping:

- `DEFAULT_JUDGE = "openai/gpt-4o-mini"` — per ADR 0143's noise
  envelope guarantee, swapping judges invalidates that envelope. Same
  guarantee will hold for LoCoMo iff we keep the same judge.
- `_REASONING_JUDGE_BLOCKLIST` + `CHIMERA_GRADE_ALLOW_REASONING_JUDGE`
  override knob — load-bearing footgun fix, do not remove.
- `max_tokens=16` for the judge call — same as upstream.

### Category-prompt mapping

LoCoMo's grading is reference-string equality (F1/EM) per
`task_eval/evaluation.py`. We use **LLM-judge** equivalence instead
(matches LongMemEval pipeline and avoids the dependency on
`bert_score`+`rouge`+`nltk`). The judge prompt templates we ship:

| Cat | Adapter label | Judge template |
|---:|---|---|
| 1 | single-hop | "yes/no — contains correct answer?" (LongMemEval `single-session-user` template, verbatim) |
| 2 | multi-hop | same as cat 1 |
| 3 | temporal-reasoning | LongMemEval `temporal-reasoning` template, verbatim (includes off-by-one tolerance) |
| 4 | open-domain | same as cat 1 |
| 5 | adversarial | LongMemEval `abstention` template, verbatim (asks "does the model identify the question as unanswerable?") |

This re-use is intentional: same judge + same prompt families = the
noise envelope characterisation in ADR 0143 stays comparable across
benchmarks. The chip's PR will document this dependency.

## CLI surface

```
chimera evals locomo \
  [--items PATH | --smoke] \
  [--sample-id ID]             # NEW vs longmemeval: filter by conv
  [--n N] [--n-per-category N] \
  [--subset CAT] \
  [--out PATH] [--mind-dir PATH] \
  [--answer] [--answer-model …] \
  [--answer-temperature T] [--answer-max-tokens N] \
  [--hybrid-retrieval] [--retrieval-top-k 8]
```

Flag parity with `chimera evals longmemeval` is the design goal;
only `--sample-id` is new (lets the operator scope a spike to a single
conversation for inspection).

## Top-k retrieval-or-not call

LoCoMo conversations are uniformly long (19–32 sessions). Two stances:

1. **Full-context default** (chosen): every session lands in the
   self-card. Matches upstream paper's evaluation setup. Cost: ~30
   sessions × avg 30 turns = ~5–10K tokens per item; manageable for
   ~30-item spike.

2. Hybrid-retrieval default. Rejected for the baseline because:
   - We need a comparison anchor against the paper's published numbers,
     which use full-context.
   - ADR 0142's `_s`-only verdict was conditional on the benchmark's
     own threshold — we should let the LoCoMo data tell us whether the
     verdict generalises rather than baking that assumption in.

The flag is available from day one; the follow-up chip can sweep both
on/off for the same items and ask "does ADR 0142's verdict generalise?".

## Pre-registered decision rules (LOCKED — do not move goalposts)

1. **Directional spike** (n-per-category, target ≈30 items): the
   chip's headline. Promotes to "LoCoMo is wired up correctly" if
   overall accuracy is non-degenerate (>20% on at least 3/5 categories).
   This is a low bar designed to catch plumbing defects, not to gate
   quality.

2. **Sanity floor**: <10% overall → suspect plumbing. Diagnose; do not
   paper over with re-attempts.

3. **Full corpus sweep**: operator-gated, **deferred** to follow-up
   chip. This chip does NOT need to clear any LoCoMo accuracy target.

## Comparison anchor (sanity, not a gate)

From the LoCoMo paper (Maharana et al. 2024), F1 / per-category numbers
for closed-source models on the full benchmark are in the 30–50%
range, with category-1 (single-hop) highest and category-5
(adversarial) lowest. Our spike's headline number lives in the same
order-of-magnitude band if everything is wired correctly; large
deviations (≪20% or ≫70%) indicate plumbing issues.

Exact reproduction is **not the goal** — judge model, prompt template,
and answerer all differ from the paper's setup. The anchor is a
sniff-check.

## Budget

| Phase | Items | Est. cost | Est. wall-clock |
|---|---:|---:|---:|
| Directional spike (n=6 per cat, all 5 cats) | 30 | ≤$2 | ~12 min |
| Full corpus sweep (deferred chip) | 1,986 | ~$5–10 | ~70 min |

Spike runs without operator authorization per existing precedent
(≤$2 / ≤30 min); full sweep is operator-gated.

## File-count budget (≤8 net-new files this chip)

1. `mind/research/locomo-design-2026-05-26.md` (this file)
2. `chimera/evals/locomo.py`
3. `scripts/grade_locomo.py`
4. `tests/test_locomo.py`
5. `mind/research/locomo-baseline-spike-2026-05-26.md`
6. `docs/adr/0144-locomo-benchmark-integration.md`

Edits (don't count as net-new):
- `chimera/cli.py` (add subparser + handler)
- `docs/adr/README.md` (add row for ADR 0144)

= 6 net-new files + 2 edits. Within charter.

## Follow-up ladder (NOT in this chip)

- **F1**: Full LoCoMo corpus sweep (1,986 items) — operator-gated.
- **F2**: Hybrid-retrieval ablation on LoCoMo (full + hybrid-retrieval
  for same items). Tells us whether ADR 0142's `_s`-only verdict
  reproduces on the second corpus.
- **F3**: Cross-benchmark σ characterisation — does ADR 0143's noise
  envelope reproduce on LoCoMo with `gpt-4o-mini` judge?
- **F4**: Dialectic-shine localisation — categorize where Chimera's
  multi-peer dialectic outperforms vs the model-strength ceiling
  observed in T2.1d.

These are mentioned in ADR 0144 §Consequences so the operator can
charter follow-ups against a known baseline.
