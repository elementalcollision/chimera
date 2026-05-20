# ADR NNNN — Short title (vM.N)

**Status:** Proposed | Accepted (YYYY-MM-DD) | Deferred (YYYY-MM-DD) | Superseded by ADR NNNN

> Delete this template header before authoring. Filename:
> `NNNN-kebab-case-title.md`, four-digit zero-padded, in numeric order.

## Context

One or two paragraphs: what observation, regression, request, or
research finding prompted this decision. Be concrete — name files,
log lines, ADR numbers, version tags. State the problem in terms a
future reader who *doesn't* have the surrounding session memory can
follow.

If this decision pairs with earlier ADRs, link them: e.g.
[ADR 0061](./0061-cross-round-parallelism-deferred.md).

## Decision

What we're doing. Use sub-sections per surface — e.g.

### Schema

```sql
ALTER TABLE foo ADD COLUMN bar INTEGER;  -- additive only when possible
```

### Code

- `chimera/path/to/file.py` — describe the new functions / classes.
- Wire into where: the call site that invokes the new code.

### CLI / dashboard

- `chimera <verb>` — the new operator surface.
- Widget at `(x, y, w, h)` — for control-plane changes.

## Tests

`tests/test_xxx.py` — 1-2 sentences per test, focus on what
behaviour each pins down.

State the full suite count after: "Full suite: N passing, M skipped
(was N-K / M, +K new)."

## Non-goals

Explicit list of what this ADR is NOT doing. Past ADRs that included
this saved a lot of "what about X" follow-up questions. Every
non-goal should answer: "we considered this and decided to defer
because ___."

## Why this shape

Optional: short rationale for the non-obvious design choices. Future
readers tend to come back asking "why didn't you just …" — answer
here.
