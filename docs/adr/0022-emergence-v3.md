# ADR 0022 — Emergence v3: auto-record + cross-host journal sync

**Status:** Accepted (2026-05-18)
**Supersedes:** the "v3 non-goals" section of [ADR 0014](0014-emergence-protocol-journal.md)

## Context

[ADR 0014](./0014-emergence-protocol-journal.md) shipped emergence as observation-only with an explicit v3 list of
non-goals: auto-record on MCP discovery, and cross-host journal sync.
v3.8 closes both.

## Decision

### Auto-record (default on)

`register_mcp_servers` calls `record_observations_from_registry(name,
reg)` after each server's tools are registered. Opt-out via
`CHIMERA_EMERGENCE_AUTORECORD=0`. Failures are caught and logged — they
do not block MCP startup.

### Cross-host journal sync

New endpoint `/emergence-feed` on the HTTP server serves the local
journal as JSONL. Each line carries an extra `source_peer_file` field so
the puller can bucket records by origin without parsing the agent_id.

The endpoint sits behind the same bearer auth as `/mcp`. `/health` and
`/healthz` remain exempt (k8s probes).

New module `chimera/a2a/emergence_sync.py`:

- `serialize_journal(dir=None)` builds the feed body.
- `sync_remote_emergence(urls=None, *, token=None, ...)` GETs the feed
  from each URL (reusing `CHIMERA_REMOTE_PEERS` + `CHIMERA_PEER_TOKEN`)
  and writes deduped records under
  `<journal_dir>/remote/<source_host>/<peer>.jsonl`. Local files are
  never touched.

CLI: `chimera emergence list` shows local + remote counts; `chimera
emergence sync` runs the pull.

### Why JSONL, not JSON

The local journal is JSONL; the feed mirrors that. Streamable, no
total-size limit on the puller side, and one malformed line doesn't
poison the rest.

## Non-goals

- No diffing across hosts. `detect_protocol_drift` still operates on
  one host's view. Cross-host alignment via emergence is future work.
- No push notifications. The feed is pull-only.
- No retention policy on `remote/` — operators rotate it if it grows.

## Tests

`tests/test_emergence_sync.py` — 5 cases:
- serialize emits one line per observation
- empty journal serializes to empty string
- `_merge_into_local` dedupes
- sync writes into the remote subtree
- sync records failures without writing

Full suite: 446 passing.
