# Known limitations and deferred work

Living document tracking gaps surfaced from real-traffic runs that
haven't yet been addressed. Each entry should link to its
remediation ADR / version once shipped.

## Open

_None._


---

## Closed

### L-2 — Shell `cwd` defaulted to `mind/`, so `state/x` landed at `mind/state/x`

**Surfaced:** v4.3 live-spin cycle 6. Agent wrote to `state/x` via a
shell call without setting `cwd`; default cwd was `mind/`, so the
file landed at `mind/state/x`.

**Closed in:** v4.4 via [ADR 0027](adr/0027-shell-default-cwd.md).
Shell default cwd switched to the mind+state common parent (repo
root) and that parent added to allowed_roots when discoverable.
Relative `state/x` and `mind/x` paths now resolve as the model
intends.

---

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
