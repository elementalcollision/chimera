# ADR 0095: Synthesis-citation grounding check

Status: Accepted
Date: 2026-05-20
Version: v4.83

## Context

The 2026-05-20 v4 long-cycle soak surfaced a fabrication failure mode
that the v4.79 artifact-validation pathway cannot catch
(mind/postmortems/soak-v4-2026-05-20.md, finding #3):

```
INBOX task A: "Read `chimera/tools/loop_guard.py` in full and summarise
               the exact heuristic for `detect_degenerate_loop`."
INBOX task B: "Based on A, form a verdict about the loop-abort logic
               and write it to `mind/research/loop-abort-investigation.md`."
```

Task A completed in 2 rounds with 1 tool call. Task B produced the
artifact (so v4.79's existence/non-empty checks both passed), but the
verdict named the buggy function as `should_abort_loop(history)` and
proposed patching a "tool-use streak counter." Neither symbol exists
in `chimera/tools/loop_guard.py` — the actual function is
`detect_degenerate_loop` and it counts *consecutive identical
tool-call signatures*, not consecutive tool_use blocks across API
turns.

The pattern: a "read" task succeeded (the file content was almost
certainly delivered to the model), but a synthesis task one or two
ACT cycles later drifted into model priors about how loop guards
generically work. The artifact existed, was non-empty, and looked
plausible — every prior check passed. The content was simply
ungrounded in the file the model claimed to have read.

v4.79 catches "did the file get written?" This ADR adds "are the
symbols in the file actually in the source the model said it read?"

## Decision

A new module `chimera/core/grounding.py` adds three controls, all
fired by `ActExecutor._execute_inner` after the existing artifact
check passes:

1. **Source-citation grounding check.** When the task text matches a
   synthesis verb (`summarise|analyse|verify|form a verdict|audit|
   review|assess|...`) AND references a source file by path
   (`.py|.ts|.tsx|.js|.rs|.go|.java|.rb|.c|.h|.cpp|.hpp`), extract
   function/class identifiers from the model's final text. Symbols
   that don't appear as whole-word matches in any cited source file
   downgrade `completed=True` to `finish_reason="ungrounded_citation"`.

   Symbol extraction matches three forms:
   - `def name` / `class Name` — code-keyword anchored.
   - "function named `name`" / "method called `name`" — prose form.
   - `` `name` `` / `` `name(args)` `` — backticked identifier.

   A length-and-shape filter (≥ 4 chars, contains underscore or mixed
   case) plus a short denylist of English / framework words drops the
   obvious false positives.

   Source-file resolution fails open: if none of the cited files can
   be read (missing fixture, path typo), the check returns an empty
   ungrounded list rather than flagging everything.

2. **Chain-of-evidence prompt scaffolding.** When the task is a
   synthesis task that cites a source file, the system prompt is
   appended with a "source-citation discipline" block requiring the
   model to quote 2-3 short verbatim snippets from the file before
   naming any symbol. Cheaper than the post-hoc check and dominates
   it in practice — a model that just quoted `detect_degenerate_loop`
   is much less likely to then attribute the bug to
   `should_abort_loop`.

3. **Re-read pathway.** The new `ungrounded_citation` finish_reason
   flows through the v4.46 escalation memory and v4.5 / v4.10
   fragmentation hook the same way `artifact_missing` does — the next
   attempt at a similar task signature starts at a higher tier, and
   the fragmentation auto-mutation pathway can propose a
   read-then-quote synthesis skill. Explicit one-shot re-read inside
   the loop is deferred; the existing fragmentation pathway already
   covers the recovery case at lower complexity.

## Consequences

- Synthesis tasks that name fabricated symbols now fail loud rather
  than producing artifacts that *look* successful. Expected effect on
  soak v5: the soak-v4 fixture task downgrades cleanly and the
  fragmentation/escalation pathway gets a chance to recover.
- False-positive surface: a synthesis text that names a real symbol
  using a non-cited file (e.g., the symbol is defined in a *different*
  file the task didn't reference) will be flagged. This is correct
  behavior — the task asked the model to read X, so citations should
  ground in X. If a future task needs cross-file synthesis, list all
  the files in the task text.
- The denylist is intentionally short; if a future task names symbols
  that match common framework primitives (`Path`, `dict`, etc.), the
  shape filter (mixed-case OR underscore, ≥ 4 chars) already drops
  most of them. Add to the denylist as patterns surface.
- No new finish_reason rows in the escalation memory's exclusion
  list — `ungrounded_citation` is a capability failure (not a budget
  failure), so it correctly triggers tier promotion.

## References

- ADR 0026 — original artifact verification (v4.3 / L-1).
- ADR 0066 — `finish_reason = "artifact_missing"` introduced.
- ADR 0093 — natural-language artifact validation + non-empty check.
- mind/postmortems/soak-v4-2026-05-20.md — finding #3 (fabrication).
- Observation 16108 — fabricated function name in loop-abort verdict.
- Observation 16113 — chip v4.83 specification.
- chimera/core/grounding.py — extraction + check + prompt scaffolding.
- chimera/core/act.py — wiring at `_execute_inner` post-artifact path.
- tests/test_act_grounding.py — unit + fixture regression tests.
