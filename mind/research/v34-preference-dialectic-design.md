# v34 (Chip T1.3): Preference-Aware Dialectic — Design Spec

## Context

**Chip T1.3** from the post-baseline priorities doc (PR #57). Closes
Failure mode B identified in the LongMemEval smoke baseline (PR #56,
30 items): single-session-preference accuracy at 20% (4/4 wrong).
Per-item review showed the model correctly identifies stated user
preferences (vegetarian, concise responses, etc.) BUT does NOT honor
them in the generated answer. The current `_DIALECTIC_PROMPT` in
`chimera/a2a/dialectic.py` asks the model to "answer the question"
without an explicit instruction to respect stated preferences.

**Sequencing**: T1.1 (evaluation harness) landed → T1.2 (temporal-aware
dialectic, ADR 0136) landed in PR #64 → T1.3 (this chip) → T1.4 (sweep)
→ T2.1 (retrieval). T1.2 added two cross-session sentences to the
initial instructions block of `_DIALECTIC_PROMPT`. T1.3 appends ONE
more sentence to the same block, AFTER T1.2's sentences, BEFORE the
"Question:" line.

## Post-T1.2 state of `_DIALECTIC_PROMPT`

The template is a single f-string in `chimera/a2a/dialectic.py` (lines 156–184)

The **initial instructions block** (everything between the opening declaration
and the blank line before `Question:`) currently contains:

1. "You are Chimera's Dialectic agent. Answer the question about peer
   \"{peer_name}\" in a single short paragraph (UNDER 120 words).
   Use ONLY the grounding below — do not invent facts. If the grounding
   doesn't support an answer, say so honestly."
2. "When the question requires information from multiple sessions,
   integrate facts across the entire history." (T1.2's sentence A)
3. "When a fact stated in an earlier session is contradicted by a later
   session, prefer the later session." (T1.2's sentence B)

Items 2 and 3 are represented as a **single logical paragraph** — T1.2
added them as two consecutive sentences without blank-line separation,
sitting after the `say so honestly.` sentence.

## Exact change: ONE sentence appended to the initial instructions block

The new sentence (suggested phrasing from PR #57):

> When the user has stated preferences about how they want to be
> answered, honor those preferences in your response.

### Placement

Append to the initial instructions block of `_DIALECTIC_PROMPT`, **after**
T1.2's two cross-session sentences, **before** the blank line that precedes
`Question: {question}`. The T1.2 sentences currently read:

```
When the question requires information from multiple sessions, integrate facts across the entire history. When a fact stated in an earlier session is contradicted by a later session, prefer the later session.
```

The new sentence appends after the second T1.2 sentence, on the same
logical paragraph — no blank line separation, matching the prose style
T1.2 established. The resulting initial instructions block becomes:

```
You are Chimera's Dialectic agent. Answer the question about peer "{peer_name}" in a single short paragraph (UNDER 120 words). Use ONLY the grounding below — do not invent facts. If the grounding doesn't support an answer, say so honestly.
When the question requires information from multiple sessions, integrate facts across the entire history. When a fact stated in an earlier session is contradicted by a later session, prefer the later session. When the user has stated preferences about how they want to be answered, honor those preferences in your response.
```

Everything after the blank line (`Question: {question}`, the peer card block,
the decisions block, the beliefs block, the KFM block, `Answer in plain
prose. No markdown, no preamble.`) is unchanged.

### Scope constraints

- `_UNKNOWN_PEER_PROMPT` is NOT modified (different code path; the
  unknown-peer framing has no user-preferences surface by design).
- No new helper functions — the change is one string literal addition.
- No new CLI flags, env knobs, or behaviour changes elsewhere.
- No modifications to T1.2's two cross-session sentences (they are
  locked; different chip).
- No rewriting of the prompt template structure — append ONE sentence,
  do NOT restructure sections.

## ADR 0137 skeleton

New file: `docs/adr/0137-preference-aware-dialectic.md`.

**Status**: Proposed

**Relationship**: Extends [ADR 0133 — Dialectic API](./0133-dialectic-api.md)
by appending a single preference-honoring instruction to the
`_DIALECTIC_PROMPT` initial instructions block. Sibling to
[ADR 0136 — Temporal-Aware Dialectic](./0136-temporal-aware-dialectic.md)
(T1.2); both are additive, non-breaking extensions to the same prompt
surface.

### Locked-design table

| Variable | Choice |
|---|---|
| **Surface** | One-sentence append to `_DIALECTIC_PROMPT` initial instructions block in `chimera/a2a/dialectic.py` |
| **Charter scope** | Four files: `chimera/a2a/dialectic.py` (one prompt extension), `tests/test_dialectic.py` (one new test), `docs/adr/0137-preference-aware-dialectic.md` (new, Proposed), `docs/adr/README.md` (one new row + count bump) |
| **Promotion gate** | single-session-preference moves by ≥20pp on smoke (post-Tier-1 sweep, T1.4) |
| **Out of scope** | Modifying `_UNKNOWN_PEER_PROMPT`; adding env knobs; appending more than one preference sentence; restructuring the prompt template; touching T1.2's locked sentences; answer-side prompt modifications |

Reference ADR 0133 (dialectic API) and ADR 0136 (temporal-aware dialectic,
T1.2 sibling).

## Test addition

Append ONE test at the end of `tests/test_dialectic.py` (extend, do NOT
create a new file):

```python
def test_build_prompt_includes_preference_sentence():
    """The preference-honoring sentence appears in build_dialectic_prompt output."""
    from chimera.a2a.dialectic import DialecticContext, build_dialectic_prompt

    ctx = DialecticContext(
        peer_name="alpha",
        peer_card_markdown="# Peer card — alpha",
        recent_decisions=[
            {
                "decision": "ALLOW",
                "reason": "handshake ok",
                "drift_score": 0.1,
                "recorded_at": "2026-05-24T10:00:00+00:00",
            }
        ],
    )
    prompt = build_dialectic_prompt(ctx, "is alpha ok?")
    assert "When the user has stated preferences about how they want to be answered, honor those preferences in your response." in prompt
```

The test mirrors the existing `test_build_prompt_includes_cross_session_sentences`
(T1.2's test) — same fixture pattern (minimal `DialecticContext` with a card
and one decision), same substring-assertion style. The new test verifies the
preference sentence appears in the assembled prompt output.

## README.md edit

`docs/adr/README.md`:

- Add one new index row for ADR 0137 immediately after the ADR 0136 row:
  ```
  | [0137-preference-aware-dialectic.md](./0137-preference-aware-dialectic.md) | ADR 0137 — Preference-Aware Dialectic (Phase 4 / item #7 follow-up): single preference-honoring sentence appended to the dialectic prompt | Proposed (2026-05-24) |
  ```
- Bump the header count from `133` to `134`:
  ```
  # ADR index

  134 architecture decision records. Listed in numeric order. ...
  ```


## READY-FOR-REMEDIATION

All design decisions locked. Charter scope is four files:
1. `chimera/a2a/dialectic.py` — append one preference-honoring sentence to `_DIALECTIC_PROMPT` initial instructions block, after T1.2's sentences, before the blank-line / `Question:`.
2. `tests/test_dialectic.py` — append `test_build_prompt_includes_preference_sentence` test.
3. `docs/adr/0137-preference-aware-dialectic.md` — new ADR (Proposed), skeleton above.
4. `docs/adr/README.md` — new index row for ADR 0137, count bump 133→134.

Implementation is a single-line string append in the f-string template. No refactors, no new helpers, no env knobs, no touching `_UNKNOWN_PEER_PROMPT`.
