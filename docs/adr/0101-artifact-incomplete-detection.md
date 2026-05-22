# ADR 0101 — `artifact_incomplete`: content-marker verification on write

**Status:** Accepted (v4.96.0)
**Date:** 2026-05-22
**Related:** ADR 0093 (NL artifact validation), ADR 0095 (citation
grounding), ADR 0096 (scope evasion), ADR 0099 (fix-without-test),
ADR 0100 (graduated trust decrements)

## Context

Soak v8 (post-mortem at `mind/postmortems/soak-v8-2026-05-22.md`)
surfaced a clean detection gap. The phase-1 INBOX task said:

> Write all of the above to `mind/research/ping-pong-wiring-investigation.md`.
> The file MUST end with a section whose heading is EXACTLY:
> `## READY-FOR-REMEDIATION`

The agent wrote a 1632-byte file. The file existed and was non-empty.
The sentinel heading was absent. The agent then reported
`completed=True`. The runner waited 15 minutes for a sentinel that
never came because nothing in the detection chain caught the omission:

| Detector | Verdict on the v8 fixture |
|---|---|
| `artifact_missing` (v4.79) | OK — file exists and is non-empty |
| `ungrounded_citation` (v4.83) | OK — no fabricated symbols |
| `scope_evasion` (v4.82) | OK — `chimera/` source untouched |
| `fix_without_test` (v4.90/v4.91) | OK — no `chimera/` writes at all |

Every detector said "ok" while the deliverable was hollow. The runner
spun for 15 minutes after the task "completed" because phase 2's gate
condition (presence of the sentinel) would never trip.

## Decision

Introduce a new `finish_reason`: **`artifact_incomplete`**.

Add a content-marker extraction helper (`expected_content_markers`) and
a content check (`check_content_markers`) next to `expected_artifacts`
in `chimera/core/act.py`. After a clean-stop completion, if every
declared artifact exists (artifact_missing passed) but any of them is
missing a required content marker the task spelled out in formal
language, downgrade `completed=True → False` with
`finish_reason="artifact_incomplete"` and populate
`incomplete_artifacts=[(path, missing_marker), ...]`.

### Why a NEW finish_reason vs EXTENDING `artifact_missing`

Considered: fold the hollow-file case into `artifact_missing` (the file
"is missing" its required content).

Rejected because:

1. **Different remediation.** `artifact_missing` says "write the file";
   `artifact_incomplete` says "append the missing section to the file
   you already wrote." Folding them would force the remediation hint to
   branch internally on file-existence anyway.
2. **Different observability.** Operators reading
   `escalation_summary()` benefit from the distinction: hollow-file
   failures imply the task text was clear enough for the agent to
   produce *something*, just not the right thing — a structurally
   different signal from "agent forgot to write."
3. **Different trust calibration.** Both currently sit at the same
   delta (1 tier), but separating them keeps that knob independent if
   future soak data shows one mode self-corrects more readily.
4. **No backward-compatibility cost.** The new reason joins
   `ESCALATING_FINISH_REASONS` and the v4.93 trust-delta table; nothing
   downstream needs to disambiguate by inspecting paths.

### Extraction conservatism

The marker patterns recognize only formal phrasings:

- ``MUST contain `<marker>` ``
- ``MUST include `<marker>` ``
- ``MUST end with `<marker>` ``
- ``heading is EXACTLY: `<marker>` ``
- ``MUST ... EXACTLY: `<marker>` ``

Markers must be backtick-quoted strings. We do not attempt to extract
bare headings, paraphrased "should contain," or colloquial "MUST."
**False-positives are worse than false-negatives** for this detector:
a false-positive blocks a clean completion; a false-negative just
reproduces v8's behaviour — which the operator can spot in the
post-mortem and tighten the task text accordingly.

## Consequences

- `ESCALATING_FINISH_REASONS` gains `artifact_incomplete`, so the
  v4.84 three-strikes auto-skip applies (same threshold, same
  chronicle warning).
- `FINISH_REASON_TRUST_DELTAS["artifact_incomplete"] = 1` — moderate,
  same as `artifact_missing` and `fix_without_test`.
- `remediation._artifact_incomplete_hint` derives a hint that names
  the specific missing marker and tells the agent to append, not
  rewrite.
- `ActResult.incomplete_artifacts: list[tuple[str, str]]` records the
  fixture for post-mortem analysis.

## Validation

Test fixtures (`tests/test_artifact_incomplete.py`):

1. v8 fixture: investigation doc *without* the sentinel → fire.
2. Positive: doc *contains* the sentinel → no fire.
3. False-positive guard: ambiguous "MUST" with no backtick-quoted
   marker → no fire.
4. Multi-marker, all present → no fire.
5. Multi-marker, one missing → fire, the missing one is named.
6. Regression: existing `artifact_missing` (file doesn't exist) still
   fires, `artifact_incomplete` does not double-fire.

## Follow-up chips

- **v4.97 (queued):** consider promoting bare on-own-line "## Heading"
  to markers when preceded by `MUST end with` or `EXACTLY` on the
  prior line. Deferred pending another fixture: the soak-v8 case is
  already covered by the backtick rule.
