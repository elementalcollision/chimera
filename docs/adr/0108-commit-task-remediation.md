# ADR 0108 — concrete-command remediation for commit tasks

**Status**: Accepted (v4.104)
**Date**: 2026-05-22
**Supersedes**: —
**Related**: 0097 (v4.84 remediation hints), 0104 (INBOX claim validity),
0107 (cross-provider witness panel)

## Context

Soak v12 ([mind/postmortems/](../../mind/postmortems/) — see commit
`a387fe8` and surrounding history) ran end-to-end and produced
[apps#1](https://github.com/elementalcollision/uberagent/pull/1) ("agent-
authored ping-pong loop detection"), but the agent's commit step itself
failed: the "Commit your changes to the current branch with `[agent]`
prefix and a one-paragraph rationale" task hit `max_rounds` twice in a
row. The dirty working tree (five `chimera/*.py` edits plus a regression
test) was preserved on the worktree and the operator stepped in to
`git add` + `git commit`, then merged the PR.

The v4.84 generic `max_rounds` hint (`chimera/core/remediation.py`,
`_max_rounds_hint`) tells the model to "call the tool that performs the
requested write on the very first round" — useful for code-edit tasks
where the tool is obvious (`code_exec`), useless for a commit task where
the tool is a shell pipeline of three or four invocations the model
keeps reasoning about instead of running.

`state/submit_pr_log.jsonl` shows the downstream v4.97 submit-pr gate
firing cleanly once the commit existed — the only missing piece in the
otherwise-autonomous loop was the act of typing `git commit`.

## Decision

Add a commit-task specialisation to `_max_rounds_hint` and `_length_hint`
in `chimera/core/remediation.py`. When `_is_commit_task(task_text)`
matches a keyword set (`commit your changes`, `git commit`, `stage and
commit`, `[agent] prefix`, plus "commit" + git/stage/branch context),
route to `_commit_remediation_hint`, which returns the literal four-step
shell invocation:

```
1. shell argv=["git", "status", "--short"]
2. shell argv=["git", "add", "<each modified path from step 1>"]
3. shell argv=["git", "commit", "-m", "[agent] <one-line subject>"]
4. shell argv=["git", "log", "--oneline", "-3"]
```

…plus a fallback for the "Please tell me who you are" identity error
the soak runner's ephemeral worktrees occasionally produce.

Concrete arguments rather than prose. The agent's shell allow-list
already permits `git` (v4.88), so the hint is directly executable.

The hint only fires on retry. First-attempt commit tasks get no
preamble — we don't want to pre-instruct on every commit; the model
usually gets it right unaided. The v4.84 escalation memory is the
trigger.

## Generalisation

This is the first instance of a broader pattern: certain task classes
(commit, run-test, file-format) benefit from concrete-command hints
over generic "try again" hints because the action is a fixed shell
pipeline, not a synthesis. v4.108+ may extend this dispatch to other
recognisable task classes (e.g. "run the test suite" → `pytest -x`).

## Non-goals

- The runner does **not** auto-run `git` from outside the agent. The
  hint just tells the model what to run; the agent still executes.
- No "wrong file selection" detection. The model picks what to stage.
  The hint warns about `mind/wiki/` cruft but doesn't enforce.
- The v4.97 submit-pr gate still validates everything before push.
  This ADR only closes the agent-side commit gap, not operator review.

## Tests

`tests/test_act_remediation.py` adds five cases pinning the dispatch:

- `test_commit_task_max_rounds_gets_concrete_hint`
- `test_commit_task_length_gets_concrete_hint`
- `test_non_commit_task_max_rounds_uses_generic_hint`
- `test_commit_task_first_attempt_no_hint`
- `test_v12_fixture_task_dispatches_to_concrete_hint` (literal v12
  task text as the input)
