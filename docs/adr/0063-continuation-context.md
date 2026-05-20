# ADR 0063 — Cross-round continuation context (v4.42)

**Status:** Accepted (2026-05-19)

## Context

The Agonistic Futures task burned 26 rounds in cycle 1 without
finishing. Cycle 2 with the same task (now re-described as "continue
from existing artifacts") finished in 16 rounds. The delta wasn't
model capability — it was that cycle 2's task text contained explicit
step-by-step structure AND named the partial artifacts. Without that
nudge, the model restarted from scratch.

[ADR 0061](./0061-cross-round-parallelism-deferred.md) (v4.40) named this as the round-boundary context loss
problem and called out adding `round_boundary_latency_ms` as the
measurement step. v4.42 ships the practical first fix: when a task
references artifact paths that already exist on disk, inject a
"Continuation context" block into the system prompt so the model
sees the partial work and treats it as authoritative.

## Decision

`ActExecutor.execute` now detects continuation context by:

1. Running `expected_artifacts(task_text)` to extract backtick-quoted
   paths under `mind/` or `state/`.
2. For each path that exists on disk, capturing `(bytes, lines,
   first 600 chars)`.
3. If any exist, prepending a "## Continuation context" block to the
   system prompt with the previews and the explicit directive:
   "CONTINUE the work (append, finish, fix) — do NOT restart from
   scratch. Treat any existing content as authoritative unless it is
   obviously truncated."

Capped at 6 paths × 600 chars to keep the prompt bounded.

### Why a system-prompt prepend, not a separate message

The block needs to be present at every model call in the round
chain, not just the first. Putting it in `system` (which Anthropic
caches) does both: visible across every round AND eligible for
prompt-cache reuse if the artifact list doesn't change within the
cycle.

### Why preview the file content vs just listing paths

Pure path listing tells the model "something exists" but not what's
in it. With a 600-char preview the model can immediately see whether
the existing content is the right shape and just needs a section
added, or is broken and needs replacing. The truncation marker is
explicit so the model knows it's seeing a head, not the full file.

## Tests

`tests/test_act.py`:

- `test_act_injects_continuation_context_for_existing_artifacts` —
  pre-seeds `mind/draft.md`, runs `execute` with task text
  referencing it, asserts system prompt contains "## Continuation
  context", the path, AND the preview text.
- `test_act_no_continuation_block_for_fresh_task` — pure unit test
  on the helper: no paths in text → empty block; path-in-text that
  doesn't exist on disk → empty block.

Full suite: 546 passing, 5 skipped (was 544 / 5, +2 new).

## Non-goals

- **Reading tool_call_history from prior cycles.** Persisting and
  replaying tool calls across the cycle boundary is a bigger change
  (needs a journal). v4.42 surfaces the *outputs* of those calls
  (the artifacts on disk), which is what the model actually needs.
- **Continuation detection by task-text similarity.** Path-based
  detection is precise; fuzzy-match would risk false positives.
- **Bounded recursion.** If a task names many artifacts and they
  collectively exceed the 6×600 cap, the rest are dropped silently.
  Fine for v4.42 — the cap can be raised if real tasks hit it.
