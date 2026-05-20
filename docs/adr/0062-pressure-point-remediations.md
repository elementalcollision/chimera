# ADR 0062 — Pressure-point remediations (v4.41)

**Status:** Accepted (2026-05-19)

## Context

Running Chimera against a real synthesis task (the Agonistic Futures
world model) surfaced three pressure points worth fixing rather than
just documenting:

1. **Dashboard Inbox widget showed empty** even when `mind/INBOX.md`
   had 14 task lines. Root cause: `lib/paths.ts` resolved REPO_ROOT
   via `path.resolve(__dirname, "..", "..")`, but Next.js compiles
   server code into `.next/server/...` where `__dirname` does not
   walk back to the repo root cleanly. `readMindFile` was silently
   pointing at a non-existent path, returning `null` / empty string,
   and the widget rendered "INBOX has no tasks."
2. **Tool-arg validation errors did not teach the model** the right
   schema. The model emitted `code_exec` with an empty `code`
   argument and got back `error: code must be a non-empty string`.
   It then retried the same broken shape several rounds in a row.
3. **mkdir race** in v4.38's skill-wiki fingerprint persistence
   still threw `FileExistsError` on macOS. The `mkdir(exist_ok=True)`
   guard isn't enough when the path already exists as a real
   directory.

## Decision

Three small targeted fixes.

### Dashboard path resolution

`lib/paths.ts` now anchors `REPO_ROOT` off `process.cwd()` (which is
`control-plane/` when launched via `npm run dev` or `next start`) and
walks up one level. Robust under both dev and prod Next.js compile
modes.

### Tool-arg validation feedback

`chimera/core/act.py::_run_one` now catches `ValueError | TypeError
| KeyError` separately from other exceptions and appends a one-line
schema hint to the tool_result content:

```
error: code must be a non-empty string
hint: code_exec({ code: string (required), timeout_s: number, cwd: string }). received keys: [].
```

A new module-level `_schema_hint(registry, tool_name, args)` helper
renders the hint from the tool's registered JSON schema (required
fields first, up to 4 optional fields). The model sees this in the
next round's tool_result and can self-correct.

### mkdir is_dir guard

`GraphStore._incremental_skills_wiki` already had the v4.38 guard
(`if not fp_path.parent.is_dir(): fp_path.parent.mkdir(...)`); this
ADR confirms it's the canonical pattern and the only correct fix on
macOS — `mkdir(exist_ok=True)` is documented to still raise
`FileExistsError` when the target exists but isn't a directory.

## Tests

`tests/test_act.py::test_act_validation_error_includes_schema_hint`
asserts the hint string reaches the next provider call's
tool_result blocks (including the `received keys: []` line so the
model can see what it actually sent).

Full suite: 544 passing, 5 skipped (was 543 / 5, +1 new).

## Non-goals

- **Teaching the model the entire registered tool catalogue in the
  system prompt.** That bloats every prompt; the per-error hint is
  cheaper and only fires when needed.
- **Auto-retry on validation failure.** The model already retries
  in the next round; the hint just makes that retry useful.
