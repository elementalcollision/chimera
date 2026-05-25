# Timestamp grounding — design note (2026-05-25)

**Chip**: Path 2 from PR #68 — surface session send-timestamps + the "today" anchor in the dialectic grounding so 77.4% of temporal-reasoning misses (the B1 hedged-ignorance + B2 zero-anchor classes from [`temporal-reasoning-regression-2026-05-25.md`](./temporal-reasoning-regression-2026-05-25.md)) recover.

**Branch**: `chip/timestamp-grounding-2026-05-25` off `d661feb`.

---

## Phase 1 findings

### Upstream schema — confirmed against `longmemeval_oracle.json`

```
keys: question_id, question_type, question, answer,
      question_date, haystack_dates, haystack_session_ids,
      haystack_sessions, answer_session_ids
```

- `question_date`: scalar string, e.g. `'2023/04/10 (Mon) 23:07'`. This is the "today" anchor for the question — the temporal-arithmetic reference point.
- `haystack_dates`: list of strings parallel to `haystack_sessions`. Each entry is the send-timestamp of session `i`.

Both fields are present on every item in the 500-item oracle set (spot-checked indexes 0, 1, 2, 250, 499 — uniform).

### What the current adapter does with them

`LongMemEvalItem.from_dict` ([chimera/evals/longmemeval.py:84](../../chimera/evals/longmemeval.py#L84)) does NOT extract `question_date` or `haystack_dates`. They land in `extra` via the catch-all dict-comprehension at L106, where nothing downstream reads them.

`LongMemEvalAdapter.ingest_history` ([chimera/evals/longmemeval.py:199](../../chimera/evals/longmemeval.py#L199)) writes:
- A synthetic self peer card with `### Session {i}` headers — no date.
- Per-session scratch markdown with `# Session {i} — {item_id}` headers — no date.

Neither surface carries any timestamp. The model literally cannot answer "how many days ago" questions because the days don't exist in its context.

### How the date will reach the model

`gather_dialectic_context` ([chimera/a2a/dialectic.py:102](../../chimera/a2a/dialectic.py#L102)) reads `mind/peers/self.md` verbatim into `ctx.peer_card_markdown`. `build_dialectic_prompt` ([chimera/a2a/dialectic.py:242](../../chimera/a2a/dialectic.py#L242)) interpolates that string directly into `_DIALECTIC_PROMPT`'s `{peer_card_block}` slot. **Therefore any text we write to `self.md` reaches the answerer with no further plumbing.** No `dialectic.py` change needed; no new template slot needed.

## Design

### Per-session date header

Each session block in the self-card gets a markdown bold header line directly under its `### Session {i}` heading:

```
### Session 0
**Session date:** 2023/04/10 (Mon) 17:50

- **user**: I just bought a new car!
- **assistant**: ...
```

Bold-prefix matches the existing `- **user**:` / `- **assistant**:` turn style. Sessions without a date (defensive fallback for non-LongMemEval inputs or malformed items) skip the header line — the existing structure is unchanged.

The same `**Session date:** ...` header is added to the per-session scratch files under `mind/wiki/longmemeval/` so a future hybrid-retrieval surface also gets the timestamp.

### Today's-date anchor

Goes at the very top of the self-card, above the `## History` heading:

```
# Peer card — self

**Today's date:** 2023/04/10 (Mon) 23:07

## History
...
```

This is the answerer's "now" — when the user asks *"how many days ago"*, the model arithmetic is `today - session_date`. Putting it at the top of the peer-card markdown means it lands at the top of `{peer_card_block}` in the assembled prompt, ahead of any session bodies, where the model encounters it before reading the history. **No `_DIALECTIC_PROMPT` change needed** — this is content insertion into an existing slot, not a template change.

Choice rationale: the alternative (adding a new `{today_date}` slot to `_DIALECTIC_PROMPT`) would require an LongMemEval-specific field on `DialecticContext` that has no meaning for production peer queries, polluting the live dialectic surface with eval-only state. Keeping the anchor inside the peer-card markdown is content-only — invisible to non-eval callers, who simply don't write a `**Today's date:**` line into their peer cards.

### Schema extension

Add two fields to `LongMemEvalItem`:

```python
question_date: str = ""
session_dates: list[str] = field(default_factory=list)
```

`from_dict` extracts both from upstream keys (`question_date`, `haystack_dates`). Default empties preserve all current call sites and tests.

### Defensive degradation

- Missing `question_date` → no top-of-card anchor written (existing behaviour).
- Missing/short `session_dates` → session header omits the date (existing behaviour). Indexing is guarded — if `session_dates` is shorter than `history`, sessions past the end render without a date.
- Both omissions together → output is byte-identical to today's adapter, so all 39 existing tests stay green.

## File-by-file changes

1. **`chimera/evals/longmemeval.py`** —
   - Add `question_date`, `session_dates` fields to `LongMemEvalItem`.
   - Update `from_dict`: read `question_date` and `haystack_dates`; pop them from the `extra` exclude-set.
   - Update `ingest_history`: emit `**Today's date:** {question_date}` at top of self-card if non-empty; emit `**Session date:** {session_dates[i]}` directly under each session header (self-card and scratch) when index is in range.

2. **`tests/test_longmemeval.py`** — add 3 new tests:
   - `test_item_from_dict_extracts_dates` — upstream keys land on the dataclass.
   - `test_ingest_writes_today_date_anchor` — self-card top contains `**Today's date:**`.
   - `test_ingest_writes_per_session_date_headers` — each session block has `**Session date:**`.
   - Plus a defensive test that items without dates still ingest cleanly (covered by existing tests; no new test required).

3. **ADR** — amend `docs/adr/0136-temporal-aware-dialectic.md` with a "2026-05-25 grounding extension" subsection. The original sentence (cross-session integration) is necessary-but-insufficient; this extension supplies the content the sentence operates on. New ADR would be artificially separated from the framing 0136 already owns.

4. **`docs/adr/README.md`** — no change (amendment, not new ADR).

## What this design deliberately does NOT do

- **No `_DIALECTIC_PROMPT` change.** Per PR #68 — failure is content, not wording.
- **No new dialectic context field.** The anchor rides inside `peer_card_markdown`.
- **No retrieval mechanism change.** T2.1 owns retrieval; this chip owns content shape.
- **No CLI flag.** Date headers are unconditional when the data is present.
- **No new modules / helpers.** Two small edits to one adapter method.

## Promotion gate (for the operator's next sweep)

Per PR #68: tighten temporal-reasoning gate to **≥68% (≥+15pp from 53.38%) AND overall ≥80% (no regression from 80.60%)**.

## READY-FOR-REMEDIATION
