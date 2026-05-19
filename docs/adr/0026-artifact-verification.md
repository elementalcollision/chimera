# ADR 0026 — Artifact verification (v4.3)

**Status:** Accepted (2026-05-19)
**Closes:** L-1 in [docs/limitations.md](../limitations.md)

## Context

ACT decided a task was "completed" purely on the model's `stop_reason ==
"stop"`. The v4.2 verification cycle exposed the gap: the model returned
`stop` for two tasks ("write to `state/fib_validation.log`", "produce
`mind/graph_db_final.md`") but neither file was actually written. INBOX
got flipped to `[x]` regardless.

## Decision

After ACT sees a `stop` response (and only `stop` — `length` /
`max_rounds` already downgrade), parse the original task text for
backtick-quoted paths under `state/` or `mind/`. If any are missing,
override `completed=False` and set
`finish_reason="artifact_missing"`, attaching the missing list to
`ActResult.missing_artifacts`.

### Why backticks under state/mind only

- **Backticks** are the markdown convention everyone already uses for
  paths and the engines / curiosity-engine output already produces them.
- **state/ and mind/** are the only two writable roots — anything else
  is either temporary or out of scope.
- Two new helpers are pure: `expected_artifacts(task_text)` and
  `check_artifacts(expected, base_dir=None)`. The dependency on `Path`
  is the only addition to ACT's import surface.

### Why post-condition, not declarative

Tasks land via free-text INBOX lines, not a structured schema. A regex
over backticks costs nothing and degrades gracefully — a task with no
backtick path simply has an empty expected set and behaves as before.
Declaring artifacts in YAML / frontmatter is a future option if the
regex starts missing real cases.

## Non-goals

- No verification of artifact *contents* — empty file with the right
  name passes. Real shape checks are downstream.
- No detection of artifacts written under unexpected paths. The
  agent's tool_call_history still records actual filesystem writes;
  surfacing those is a separate dashboard improvement.
- Tasks that legitimately don't produce files (a pure narrative
  summary in the chronicle, an alignment ceremony) carry no
  backtick-paths and are unaffected.

## Tests

`tests/test_artifact_verification.py` (6 cases):
- extracts both paths from a multi-artifact task
- dedupes repeats
- ignores backticks around non-path strings (e.g. `` `code_exec` ``)
- ignores absolute paths
- `check_artifacts` returns only the missing paths
- empty result when everything present

`tests/test_act.py` adds 2 integration cases:
- task with `state/missing.log` → `completed=False`,
  `finish_reason="artifact_missing"`, `missing_artifacts` populated
- task with an existing path → completes normally

Full suite: 461 passing.
