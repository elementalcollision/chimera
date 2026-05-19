# ADR 0016 — Graph-powered features (v3.0)

**Status:** Accepted (2026-05-18)
**Builds on:** [ADR 0015](0015-graph-store.md)

## Context

ADR 0015 introduced LadybugDB as a derived projection over SQLite. v2.10 populated only the
KFM-shaped subset: `Entity`, `Mutation`, `ApiCall`, `Peer`, `TRANSITIONED_TO`. The four
filesystem-only edge types — `DEPENDS_ON`, `USES_TOOL`, `REFERENCES`, plus the `Skill` and
`WikiDoc` node tables — were declared but unpopulated.

v3.0 closes that gap and adds the first canned queries that operators will actually run.

## Decision

### Projections (added in `GraphStore._project_skills_and_wiki`)

- **`Skill`** node per `.py` module in `chimera/tools/dynamic/` (filename = skill name).
- **`DEPENDS_ON`** edge: AST scan for `from chimera.tools.dynamic import X` and
  `from chimera.tools.dynamic.X import …` — point the importing skill at the imported skill.
- **`USES_TOOL`** edge: AST scan for string literals matching a core-registry tool name; edge
  Skill→Entity where Entity.kind='tool' and Entity.name matches.
- **`WikiDoc`** node per `*.md` under `mind/`, keyed by path relative to `mind/`.
- **`REFERENCES`** edge: parse markdown `[…](target.md)` links; resolve relative to the
  source doc; skip http(s) targets and self-loops.

Called automatically at the tail of `rebuild_from_sqlite`. Idempotent; `clear_all` now uses
`DETACH DELETE` so node tables clear cleanly even when edges exist.

### Canned-query CLI

- `chimera graph entity-history <id-or-name>` — full TRANSITIONED_TO chain, ordered by cycle.
  Accepts entity name, full id, or 8-char id prefix.
- `chimera graph skill-deps` — every Skill with its outgoing DEPENDS_ON / USES_TOOL edges.
- `chimera graph orphans` — Entities with no transitions; Skills with no edges. Surfaces
  dead code and stagnant KFM entries.

These exist alongside the raw `chimera graph query "<cypher>"` for ad-hoc work.

### Tests

`tests/test_graph_store.py` gains two cases:
- `test_filesystem_projection_skills_and_wiki` — exercises all three new edge types using
  tmp_path-scoped skills and mind directories.
- `test_entity_history_query_returns_ordered_chain` — verifies the underlying Cypher used
  by `entity-history`.

## Non-goals

- **No live projection.** Filesystem changes still require an explicit `chimera graph rebuild`.
- **No `PROPOSED` / `ACTIVATED` / `TRUSTED` edges yet.** Those need cross-store joins
  (mutation payload → entity name; trust-history events → peer pairs) that are real but not
  urgent. Deferred to v3.1 if/when a use case appears.
- **Vector index untouched.** The Qdrant deferral trigger from ADR 0002 still rules.

## Sources

- [`docs/adr/0015-graph-store.md`](0015-graph-store.md)
- [`chimera/memory/graph.py`](../../chimera/memory/graph.py)
