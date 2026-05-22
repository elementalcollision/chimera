# ADR 0105 — syntax-invalid detection on agent writes

**Status**: Accepted (v4.101)
**Date**: 2026-05-22
**Supersedes**: —
**Related**: 0099 (fix-without-test), 0101 (artifact incomplete),
0103 (phase-scope fix-without-test), 0104 (INBOX claim validity)

## Context

Soak v10 (mind/postmortems/soak-v10-2026-05-22.md, Failure section)
reached phase 2 cleanly — a v4.98 win — and the agent attempted to wire
`detect_ping_pong` into `chimera/core/act.py`. The edit was structurally
invalid Python: a `return ActResult(` was opened, then a dedented
`verdict = detect_degenerate_loop(history)` interrupted the function
call, then kwargs continued as if still inside the original `return`.
Result: `SyntaxError` on import.

The exact failing fixture is preserved at
`/Users/dave/chimera-soak-v10-2026-05-22-1731/chimera/core/act.py`
(uncommitted, around line 1524) and at `/tmp/v10-broken-act.py`.

None of the 13 existing detectors caught the broken write:

- **v4.92 fix_without_test**: never ran (task hit `scope_evasion` first).
- **v4.96 artifact_incomplete**: no content marker on `act.py`.
- **v4.99 phase_fix_without_test**: phase 2 never ended cleanly.
- **v4.100 inbox_claim_invalid**: agent didn't flip `[x]` for the task.
- **v4.82 scope_evasion** fired correctly, but it only validates WHERE
  the agent wrote, not WHAT was written.

The runner spent 13 minutes spinning on identical
`SyntaxError: invalid syntax` tracebacks at module import time before
the operator killed it. The trust ladder degraded T5 → T1 in cycle 131
without auto-promote firing — a related concern out of scope here.

## Decision

Add a `syntax_invalid` detector to the ACT completion-check sequence.
After the agent declares a task done, every `*.py` path in
`write_targets` is run through `python3 -m py_compile`. Files that fail
compilation cause:

- `completed = False`
- `finish_reason = "syntax_invalid"`
- `ActResult.syntax_failures` populated with `[(path, error_msg), ...]`
- escalation row recorded (it joins `ESCALATING_FINISH_REASONS`)
- one-tier trust demote (same severity as `fix_without_test`)
- v4.84 remediation hint naming the offending path(s) and parse error
- three-strikes auto-skip available via the normal v4.84 path

### Ordering

The check runs **before** `check_fix_without_test`. If syntax is broken,
fixing that is the actionable next step regardless of whether a test
exists — emitting `fix_without_test` would mislead the model into
writing tests against an unimportable module. The sequence is:

```
expected_artifacts/markers → scope_evasion → ungrounded_citation
  → syntax_invalid                ← NEW (v4.101)
  → fix_without_test
  → inbox_claim_invalid
```

### Detector contract

```python
def check_syntax_valid(write_targets: list[str]) -> list[tuple[str, str]]:
    """Returns [(path, error_msg), ...] for any *.py path in
    write_targets that fails python compilation."""
```

- Non-`.py` paths are ignored (Markdown can contain `def foo(:`).
- Nonexistent paths are ignored (the writer reports paths the agent
  *attempted to write*; some attempts produce no file).
- A 5-second timeout per file caps worst-case wall time.
- Stderr from `py_compile` is captured; the last non-empty line is
  used as the error message (this is the `File "X", line N\n    ...`
  shape `py_compile` produces).

## Consequences

**Positive**

- The exact soak-v10 failure no longer reaches the runner's import
  step. The agent gets a remediation hint naming the broken file and
  line, and a tier demote — recoverable in a single retry for the
  common case (missing parenthesis, dedent error, stray statement).
- Three-strikes auto-skip prevents the 13-minute spin observed in
  soak v10. After three identical syntax_invalid escalations on the
  same task signature, ACT short-circuits with an operator-visible
  chronicle warning.
- The detector is cheap (sub-100ms per file under normal load) and
  pure with respect to ACT state — it only reads files.

**Negative**

- Adds a subprocess invocation per writing task. Bounded: only `.py`
  paths, only existing ones, 5s timeout.
- Does NOT catch runtime errors (NameError, ImportError of a missing
  symbol). py_compile only validates parse-time correctness. Runtime
  validation is out of scope; the next layer is test execution.
- A malformed file the agent wrote and then deleted before the check
  is missed (we ignore nonexistent paths). This is the rare case;
  more importantly it can't crash the runner because the file isn't
  on disk.

## Out-of-scope (v4.102 follow-up)

Soak v10 also surfaced that the v4.95 degrade-check runs at the cycle
boundary, not after each escalation. The trust ladder collapsed T5 → T1
*within* cycle 131 without auto-promote firing. The fix is either:

1. Re-run the v4.95 degrade-check hook after every escalation, OR
2. Cap the per-cycle trust decrement in v4.93 (graduated decrements).

Either is straightforward; both are out of scope for v4.101. Filing as
a separate chip.

## References

- Soak v10 post-mortem: `mind/postmortems/soak-v10-2026-05-22.md`
- Fixture (worktree, uncommitted): `/Users/dave/chimera-soak-v10-2026-05-22-1731/chimera/core/act.py`
- Fixture (frozen copy): `/tmp/v10-broken-act.py`
- Detector: `chimera/core/act.py::check_syntax_valid`
- Tests: `tests/test_syntax_invalid.py`
- Trust delta: `chimera/trust/manager.py::FINISH_REASON_TRUST_DELTAS["syntax_invalid"] = 1`
- Remediation hint: `chimera/core/remediation.py::_syntax_invalid_hint`
