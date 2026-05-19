# ADR 0025 — v4.0 stability promises

**Status:** Accepted (2026-05-19)

## Context

Chimera has shipped 30+ minor releases across v1.0 → v3.11, with 24 ADRs
along the way. The shape of every persistent surface (SQLite, graph,
mind/, peer registry, peer-trust journal, emergence journal, HTTP
endpoints) is now exercised end-to-end. v4.0 cuts the line that says
"this is what callers and operators can rely on".

## What v4 promises

These surfaces have stamped versions or otherwise fixed contracts.
Bumping any of them requires a follow-up ADR.

### Persistent state

| Surface | Version | Stamp |
|---|---|---|
| `state/chimera.db` SQLite tables | `SQLITE_SCHEMA_VERSION = 4` | `PRAGMA user_version` |
| `state/chimera.graph/` LadybugDB | `GRAPH_SCHEMA_VERSION = 1` | constant |
| `~/.chimera/peers/*.json` | `REGISTRY_SCHEMA_VERSION = 1` | per-entry field |
| `state/peer_trust_journal/*.jsonl` | append-only JSONL | implicit (line shape) |
| `state/protocol_journal/*.jsonl` + `remote/<host>/` | append-only JSONL | implicit |
| `state/phase_timings.json` | `{cycle, completed_at, phase_times_ms}` | implicit |
| `state/chimera.graph.snapshot.json` | `{generated_at, entities, skills, ...}` | implicit |

Tables and constants are now part of the public contract. Adding new
tables / nullable columns is non-breaking; renaming or dropping is a
schema-version bump.

### Mind layout

- `mind/HEARTBEAT.md` — YAML frontmatter is the public shape
- `mind/INBOX.md` — `- [ ]` / `- [x]` markdown checklists
- `mind/CHRONICLE.md` — append-only narrative
- `mind/SESSION_LOG.md` — append-only
- `mind/wiki/{lessons,plans,projects}/*.md` — graph projection input

### Environment variables

Documented and stable: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
`CHIMERA_AGENT_ID`, `CHIMERA_MIND_DIR`, `CHIMERA_STATE_DIR`,
`CHIMERA_MCP_SERVERS`, `CHIMERA_PEER_REGISTRY_DIR`,
`CHIMERA_PEER_TRUST_JOURNAL_DIR`, `CHIMERA_PROTOCOL_JOURNAL_DIR`,
`CHIMERA_REMOTE_PEERS`, `CHIMERA_PEER_TOKEN`, `CHIMERA_PEER_TOKENS`,
`CHIMERA_PEER_EXPOSED_TOOLS`, `CHIMERA_GLOBAL_TOOL_DENY`,
`CHIMERA_LOG_JSON`, `CHIMERA_LOG_LEVEL`, `CHIMERA_EMERGENCE_AUTORECORD`,
`CHIMERA_OPUS_PLAN_EVERY_N`, `CHIMERA_CYCLE_SECONDS`,
`CHIMERA_SESSION_MAX_HOURS`, `CHIMERA_DISCOVERY_HOUR`,
`CHIMERA_CURIOSITY_HOUR`, `CHIMERA_REFLECTION_HOUR`,
`BRAVE_SEARCH_API_KEY`, `EXA_API_KEY`.

### HTTP endpoints

- `GET /health` → `200 text/plain` `chimera ok`. Always anonymous.
- `GET /healthz` → `200 application/json` `{status, version, agent_id,
  capabilities, cycle, trust_tier, session_started_at, db}`. Always
  anonymous (k8s probes).
- `GET /emergence-feed` → `200 application/jsonl`. Bearer-auth.
- `Mount /mcp` → MCP `StreamableHTTPSessionManager`. Bearer-auth.

### CLI verbs

`status`, `doctor`, `run`, `ping`, `serve [--http]`, `ontology`,
`mutations {list,show,approve,reject}`, `a2a {identity,peers}`,
`peers {list,forget,sweep,kfm,sync,sweep-remote}`,
`trust {show,promote,demote,lockdown}`,
`skills {list,assemble}`, `engines run <name>`,
`scenario {drift,research,two_chimera,multi_host}`,
`graph {init,query,rebuild,entity-history,skill-deps,orphans,
provenance,export}`, `emergence {list,sync}`.

## What is NOT promised in v4

- The Python module API outside `chimera.memory`, `chimera.a2a`,
  `chimera.core`, and `chimera.providers` may still move. Type
  annotations and dataclass field order are not stable.
- The dashboard JSON shapes are still iterating.
- Provider tier ladders may add/remove rungs as model availability
  changes.
- The drift composite formula is subject to tuning.

## Breaking changes between 3.x and 4.0

None. v4.0 is a checkpoint, not a rewrite. Every test from v3.11 passes
on v4.0.

## Tests

`tests/test_schema_migration.py` — 6 cases:
- fresh DB stamps `user_version = SQLITE_SCHEMA_VERSION = 4`
- re-init is idempotent
- all six tables present after init
- legacy v0 DB (single `entities` table) upgrades cleanly on open
- graph schema version constant is 1
- `GraphStore.init_schema()` is idempotent

Full suite: 453 passing.
