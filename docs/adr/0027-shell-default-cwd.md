# ADR 0027 — Shell default cwd is the mind+state common parent (v4.4)

**Status:** Accepted (2026-05-19)
**Closes:** L-2 in [docs/limitations.md](../limitations.md)

## Context

Until v4.3 the shell tool defaulted `cwd` to the mind directory. The
v4.3 live-spin showed that the model would write to `"state/x"` via
a Python `open(...)` call without setting `cwd`, and the file would
land at `mind/state/x` instead of `state/x`. v4.3 artifact
verification correctly flagged the declared path as missing, but the
stray file polluted the mind tree until a manual cleanup.

## Decision

Add the **common parent** of mind/ and state/ (typically the repo
root) to the shell sandbox's allowed roots when both subdirs share a
parent. Switch the default cwd to that parent. Relative paths
`"state/x"` and `"mind/x"` now resolve correctly from a single cwd.

- `_allowed_roots()` returns `[mind, state]` always, plus the common
  parent when discoverable.
- `_default_cwd()` returns the common parent when present, else mind
  (preserves prior semantics for split layouts where mind and state
  live under different roots).
- `_resolve_cwd(cwd_arg)` uses `_default_cwd()` both as the default
  when `cwd_arg is None` AND as the base for resolving relative
  cwd values.

The schema description was updated to match: "defaults to the repo
root, so relative paths 'state/x' and 'mind/x' both resolve as
expected".

## Why not "magically rewrite state/ paths"

The remediation doc listed three options; (2) was magical (rewrite
`state/x` to the state root when cwd=mind). It would surprise any
non-LLM caller of the shell tool. Option (1) — make the cwd correct —
keeps shell behaviour predictable for both humans and models.

## Non-goals

- The shell subprocess can still write anywhere its uid permits via
  absolute paths. The sandbox is a cwd restriction, not a filesystem
  capability boundary. That's unchanged.
- No retroactive cleanup of `mind/state/` trees left by prior cycles.
  Documented; operators remove manually.

## Tests

`tests/test_tools.py` gains:
- `test_shell_default_cwd_is_common_parent_of_mind_and_state` —
  verifies `_default_cwd()` returns the parent and relative path
  resolution lands in the right place.
- `test_shell_default_cwd_falls_back_when_no_common_parent` — split
  layouts still default to mind.
- `test_shell_ls_at_default_cwd_sees_both_mind_and_state` — sanity.

Three existing tests were updated to pass `cwd="mind"` explicitly
where they previously relied on the old mind-is-default behaviour
(`test_shell_runs_safe_command`, `test_register_shell_tool_then_dispatch`,
`test_call_tool_dispatches_when_exposed`). One test
(`test_shell_rejects_cwd_outside_roots`) now uses a path under a
fresh tmp root so it's genuinely outside.

Full suite: 464 passing.
