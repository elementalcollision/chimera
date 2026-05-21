# ADR 0097: Post-escalation remediation hints + three-strikes auto-skip

Status: Accepted
Date: 2026-05-20
Version: v4.84 (lands in the 4.84.0 release)

## Context

The 2026-05-20 v5 long-cycle soak (`mind/postmortems/soak-v5-2026-05-20.md`)
confirmed that the *detection* layer is now solid:

- v4.79/v4.81 — `artifact_missing` fires on phantom completions.
- v4.82 (ADR 0096) — `scope_evasion` fires when a named code path goes
  unedited (2 confirmed in v5).
- v4.83 (ADR 0095) — `ungrounded_citation` guards against fabricated
  symbols in synthesis output.

But the *recovery* layer is empty. The exact retry pattern observed
across cycles 130–138:

```
ACT: 'Write a regression test in tests/test_loop_guard.py...'
     → scope_evasion (rounds=6, tools=11, completed=False)
ACT: 'Write a regression test in tests/test_loop_guard.py...'
     → length        (rounds=20, tools=26, completed=False)
ACT: 'Write a regression test in tests/test_loop_guard.py...'
     → length        (rounds=12, tools=18, completed=False)
```

v4.82 caught the failure on attempt 1. Attempts 2-3 hit `length`
(max output tokens) because the model — receiving the *same task text*
with no diagnosis of the prior failure — kept writing extensive
analysis prose instead of calling `code_exec` to write the file. The
`task_escalations` table had the verdict (`scope_evasion: didn't
write to tests/test_loop_guard.py`), but the next attempt's prompt
never surfaced it to the model.

The same shape recurred in soaks v2–v4 with different finish reasons.
The structural fix is to close the feedback loop: when a task
escalates, the next attempt's prompt should carry a finish-reason-
specific hint that names the path, artifact, or symbol the prior
attempt mishandled.

## Decision

Three coordinated changes in v4.84:

### 1. Finish-reason → remediation hint mapping

New module `chimera/core/remediation.py` exposes
`derive_remediation_hint(task_text, finish_reason)` which returns a
one-paragraph hint specific to the failure mode. The hint is
derived from the *task text* (no schema changes to
`task_escalations`), reusing existing path/artifact/source-file
extractors:

- `scope_evasion`: names the path via `intended_code_paths()` and
  instructs the model to call `code_exec` or `shell` against it.
  *"Your previous attempt at this task reported completed=True but
  did NOT write to `tests/test_loop_guard.py`. Use the code_exec
  tool now to create that file. Don't analyse — write."*
- `artifact_missing`: names the artifact via `expected_artifacts()`
  and demands the file be written before completion.
- `ungrounded_citation`: names the source files via
  `extract_cited_source_files()` and demands verbatim symbol
  citations.
- `max_rounds` / `length` / `degenerate_loop_abort`: pushes
  tool-first behaviour; reduce analysis prose.
- Other (unknown) finish reasons: a generic hint that surfaces the
  reason string and instructs a tool-first retry.

Non-actionable exits (`cost_cap`, `rolling_hour_cap`,
`task_budget`, `provider_unavailable`, `stop`) return `None` — no
preamble is added.

### 2. Hint injection at task seed

`ActExecutor.execute()` (chimera/core/act.py) consults
`remediation_decision()` immediately after the existing
`recommended_tier()` lookup. If a decision carries a non-empty
preamble, it is prepended to the *user message*:

```
<!-- prior attempt 1 failed: scope_evasion (tier=haiku, rounds=6) -->
Your previous attempt at this task reported completed=True but did
NOT write to `tests/test_loop_guard.py`. ...

<original task text>
```

Prepending on the user message (not the system prompt) keeps the
diagnosis in the model's immediate context window even after long
tool-use sequences.

### 3. Three-strikes auto-skip + chronicle warning

After 3 same-signature failures (`THREE_STRIKES_THRESHOLD = 3`),
`ActExecutor.execute()` short-circuits before calling any provider:

- Returns `ActResult(completed=False, rounds=0,
  finish_reason="skipped_three_strikes")`.
- The new `SKIPPED_THREE_STRIKES` finish reason is *not* in
  `ESCALATING_FINISH_REASONS` — recording it would ratchet the
  counter up forever.
- Writes an operator-visible warning to `mind/CHRONICLE.md` under
  today's date in an `Escalation Warnings` section via the
  Chronicle handle wired in from `ChimeraLoop`.

The 2-strike preamble already escalates sternness: the third
attempt's preamble includes *"This is your final retry. You MUST
call a write tool (code_exec or shell) this round; analysis-only
responses will be rejected."*

### 4. `length` added to ESCALATING_FINISH_REASONS

Without this, the soak-v5 retry pattern (`scope_evasion → length →
length`) would only ever count as 1 strike — three-strikes auto-skip
would never trigger. `length` is also a real capability signal: the
model needed more output budget than the tier allotted, so tier
promotion via the existing `recommended_tier()` ladder is justified.

## Consequences

**Positive**

- Closes the recovery-layer gap. The next soak (v6) should show
  scope_evasion firing once, the hint surfacing in the retry
  prompt, and the model using `code_exec` on the named path —
  with `git diff --stat` showing the named source file as modified.
- Bounded retry policy. Three strikes is a hard stop; budget burn
  on stuck tasks is capped at ~3× the per-task budget instead of
  the unbounded retry seen in soaks v2–v5.
- Operator visibility. Chronicle warnings surface stuck tasks
  during normal `mind/CHRONICLE.md` review, not buried in
  `task_escalations` rows.
- No schema changes. The hint derivation reads from `task_text`
  via existing extractors; the `task_escalations` table stays as
  it is.

**Negative / Risks**

- Hint text adds ~100-200 tokens to retry prompts. Acceptable
  given the alternative is full max-output bursts of analysis.
- The hint is best-effort: if the task text is unusual (no
  backticked paths, no write verbs), the extractor returns empty
  and the hint falls back to a generic "did not write the expected
  artifact" form. Still better than nothing.
- Three-strikes skip is per-cycle; operators must rewrite the
  INBOX line or split the task to clear the escalation history
  (`chimera state escalations clear --signature <sig>` exists from
  v4.48).

**Telemetry**

`logger.warning` is emitted on the three-strikes branch with the
match count. No new database rows. The chronicle warning is the
durable operator-facing signal.

## Validation

Tests in `tests/test_act_remediation.py` (18 cases):

- Each finish reason → hint includes the expected path/artifact/source.
- Non-actionable reasons → `None`.
- Three same-signature failures → `RemediationDecision(skip=True)`.
- `ActExecutor.execute()` with 3 priors → returns
  `SKIPPED_THREE_STRIKES`, writes a chronicle `upsert_section` call,
  and never touches the provider.
- `SKIPPED_THREE_STRIKES` is asserted *not* in
  `ESCALATING_FINISH_REASONS`.

Pairs with v4.85 (the v4.82 path-extraction regex multi-line fix);
both land before soak v6.
