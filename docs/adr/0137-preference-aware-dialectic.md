# ADR 0137 — Preference-Aware Dialectic

**Status**: Accepted (2026-05-25)

> Promotion gate cleared: ADR 0137's locked-design table required single-session-preference move **≥20pp** on the post-Tier-1 sweep; observed **+30pp** (20.00% → 50.00%) on the 500-item full sweep. See [`mind/research/longmemeval-baseline-2026-05-25.md`](../../mind/research/longmemeval-baseline-2026-05-25.md).

## Context

Chip T1.3 from the post-baseline priorities doc (PR #57). Closes
Failure mode B identified in the LongMemEval smoke baseline (PR #56,
30 items): single-session-preference accuracy at 20% (4/4 wrong).
Per-item review showed the model correctly identifies stated user
preferences (vegetarian, concise responses, etc.) BUT does NOT honor
them in the generated answer. The current `_DIALECTIC_PROMPT` in
`chimera/a2a/dialectic.py` asks the model to "answer the question"
without an explicit instruction to respect stated preferences.

## Decision

Append a single preference-honoring sentence to the initial
instructions block of `_DIALECTIC_PROMPT`, after T1.2's two
cross-session sentences, before the blank line that precedes
`Question:`.

The new sentence:

> When the user has stated preferences about how they want to be
> answered, honor those preferences in your response.

## Locked-design table

| Variable | Choice |
|---|---|
| **Surface** | One-sentence append to `_DIALECTIC_PROMPT` initial instructions block in `chimera/a2a/dialectic.py` |
| **Charter scope** | Four files: `chimera/a2a/dialectic.py` (one prompt extension), `tests/test_dialectic.py` (one new test), `docs/adr/0137-preference-aware-dialectic.md` (new, Proposed), `docs/adr/README.md` (one new row + count bump) |
| **Promotion gate** | single-session-preference moves by \u226520pp on smoke (post-Tier-1 sweep, T1.4) |
| **Out of scope** | Modifying `_UNKNOWN_PEER_PROMPT`; adding env knobs; appending more than one preference sentence; restructuring the prompt template; touching T1.2's locked sentences; answer-side prompt modifications |

## References

- [ADR 0133 — Dialectic API](./0133-dialectic-api.md)
- [ADR 0136 — Temporal-Aware Dialectic](./0136-temporal-aware-dialectic.md) (T1.2 sibling)
