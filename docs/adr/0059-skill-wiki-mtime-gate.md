# ADR 0059 — Skill/wiki incremental via mtime gate (v4.38)

**Status:** Accepted (2026-05-19)

## Context

ADRs 0053 (v4.31) and 0057 (v4.35) left skill / wiki projection as
"operator-triggered full rebuild only" because they're filesystem-
scan heavy: walk `dynamic_skills_dir()` for `.py`, AST-parse each,
walk `mind/**/*.md`, regex-scan each for refs. On a fresh repo
that's fast; with hundreds of files it becomes the dominant cost in
`rebuild_from_sqlite`.

[ADR 0054](./0054-housekeeping-graph-update.md) (v4.32) wired `update_from_sqlite` into every cycle's
housekeeping phase. If skills/wiki ran on every cycle it would
re-scan files on every tick. Instead, v4.38 introduces an mtime gate
so the work is skipped when nothing on disk has changed.

## Decision

`GraphStore._incremental_skills_wiki()`:

1. Walk `skills_dir/*.py` and `mind/**/*.md`, collect
   `(filepath, st_mtime_ns)` tuples, sort, SHA1-hash.
2. Read the previous fingerprint from
   `<graph_path>/.skills_wiki_fingerprint`.
3. If the fingerprint matches the cache → return `{}` (no-op).
4. If it differs → `MATCH (n:Skill|WikiDoc) DETACH DELETE n`,
   re-run `_project_skills_and_wiki` (which produces all four edge
   tables), write the fresh fingerprint to disk.

Wired into `update_from_sqlite` behind `include_skills_wiki=True`
(the new default). Callers that want strict append-only semantics
pass `False`.

### Why fingerprint vs per-file mtime check

The projection is structurally global — skill A's `DEPENDS_ON` edge
to skill B is invalidated if A's source OR B's existence changes.
A whole-tree fingerprint is the right granularity. Per-file
incremental projection of AST edges is much more complex and not
worth it at this scale.

## Tests

`tests/test_graph_store.py::test_update_skills_wiki_mtime_gate_is_noop_when_unchanged`:
- Two consecutive `update_from_sqlite` calls with no filesystem
  changes; second call's counts dict has no `WikiDoc` key (work
  was skipped).
- Fingerprint file written with sha1 hex digest (40 chars).

Full suite: 538 passing.

## Non-goals

- **Per-file detection.** A whole-tree hash is fine for the
  hundreds-of-files scale Chimera operates at.
- **Optimistic incremental.** No partial projection — when the
  hash changes, the entire skill/wiki subgraph is replaced.
  Simpler and correct.
