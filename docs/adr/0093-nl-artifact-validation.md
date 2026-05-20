# ADR 0093: Natural-language artifact validation + non-empty check

Status: Accepted
Date: 2026-05-20
Version: v4.79

## Context

The 2026-05-20 v2 long-cycle soak test surfaced a repeating failure
shape in the glossary / loop-abort-investigation task:

```
ACT: 'Write all of the above to' → max_rounds (rounds=12, tools=16, completed=False)
ACT: 'Write all of the above to' → stop       (rounds=2,  tools=2,  completed=True)
```

The retry reported `completed=True` after two short rounds — but the
promised file (`mind/research/loop-abort-investigation.md`) was not
present in the worktree afterwards. The likely chain: the model hit a
shell-allowlist denial on `mkdir` or a similar precondition, emitted a
brief explanatory turn, and stopped. ACT (chimera/core/act.py) treated
`stop_reason="stop"` as "task done" without validating that the
promised artifact actually existed.

The v4.3 artifact-verification path (ADR 0026) already exists, but only
fires when the task text contains a **backtick-quoted** path under
`state/` or `mind/`. Several real task lines reach ACT without
backticks, and any partial write that creates the file with zero bytes
also slips past the existing existence check.

## Decision

Extend `chimera.core.act.expected_artifacts` and `check_artifacts`:

1. **Natural-language extraction.** Add a verb-prepositional pattern —
   `(write|save|put|store|create|emit|output|append|persist)` ... `(to|at|into|in)` <path> —
   that captures un-backticked paths. To control false positives, the
   captured path must:
   - live under a trusted root (`state/`, `mind/`, `docs/`),
   - include a file extension (1–6 alnum chars),
   - sit within ~120 chars of the verb, and
   - the verb must be word-boundary anchored (so `overwrite` doesn't
     match).

2. **Non-empty file check.** A zero-byte file is now treated as
   missing. Same with a path that resolves to a directory rather than
   a file. The soak test showed shell-allowlist partial denials can
   leave a touched-but-empty file behind; behavioural parity with "no
   file at all" is what callers want.

3. **Re-use existing telemetry.** No change to `finish_reason` —
   `artifact_missing` (ADR 0066) already flows into the v4.46
   escalation memory and the fragmentation auto-mutation hook.

The new `docs/` root is permitted in the trusted-roots list because
several existing tasks write to `docs/`; it has the same in-repo
locality as `mind/` and `state/`.

## Consequences

- Tasks phrased in natural English now trigger the same validation as
  the backticked canonical form. This will surface as additional
  `artifact_missing` rows in `cycle_history` and additional escalations
  in the v4.46 memory — operators should expect the first few cycles
  after deployment to look "noisier" until the pattern is absorbed.
- The zero-byte rule could theoretically reject legitimate empty
  artifacts (e.g., a deliberately empty sentinel). None exist in the
  current task corpus; if a future task needs one, switch its
  verb/preposition to "touch" or quote the path differently.
- False-positive surface is bounded by the trusted-roots prefix + the
  required file extension. Tested against task lines that mention
  `/etc/passwd`, bare directory references, and `overwrite`-style
  prose — none match.

## References

- ADR 0026 — original artifact verification (v4.3 / L-1).
- ADR 0066 — `finish_reason = "artifact_missing"` introduced.
- ADR 0090 — proposer acceptance scoring (telemetry consumer).
- Observation 15949 — bug surfaced in v2 soak run.
- chimera/core/act.py — `expected_artifacts`, `check_artifacts`.
- tests/test_act_artifact_validation.py — pattern + non-empty tests.
