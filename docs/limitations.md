# Known limitations and deferred work

Living document tracking gaps surfaced from real-traffic runs that
haven't yet been addressed. Each entry should link to its
remediation ADR / version once shipped.

## Open

### L-2 — Shell `cwd` defaults to `mind/`, so `state/x` lands at `mind/state/x`

**Surfaced:** v4.3 live-spin cycle 6. INBOX task asked to write to
`state/fib_validation.log`. Agent ran a `python -c '… open("state/…", "w") …'`
shell call without setting `cwd`. Shell's default cwd is `mind/` (per
the existing schema), so the file landed at `mind/state/fib_validation.log`.
v4.3 artifact verification correctly flagged `state/fib_validation.log`
as missing, but the underlying issue is that the model + sandbox interpret
the same relative path differently.

**Impact:** Agents writing to "state/…" effectively create a parallel
hierarchy under `mind/state/…`. v4.3 catches the false-completion but
the leftover file pollutes the mind tree until manually cleaned.

**Path to fix:** Three options ranked by surgical-ness:
1. Add the repo root (common parent of `mind/` and `state/`) to the
   shell sandbox's allowed roots and switch the default cwd there. The
   shell tool then naturally resolves "state/x" and "mind/x" correctly.
2. Have the shell tool re-route a relative path starting with `state/` to
   the actual state dir when default cwd is `mind/`. Magical; surprising.
3. Drop default cwd entirely — force the agent to be explicit. Cheap;
   noisy.
Recommend (1).


---

## Closed

### L-1 — `completed=True` doesn't verify promised artifacts

**Surfaced:** v4.2 verification cycle. ACT reported
`completed=True` on `stop_reason="stop"` regardless of whether the
promised files (`state/fib_validation.log`,
`mind/graph_db_final.md`) actually landed.

**Closed in:** v4.3 via [ADR 0026](adr/0026-artifact-verification.md).
`expected_artifacts(task_text)` extracts backtick-quoted paths under
`state/` / `mind/`; ACT checks each one exists after `stop` and
downgrades to `finish_reason="artifact_missing"` with the missing
list when any are absent.
