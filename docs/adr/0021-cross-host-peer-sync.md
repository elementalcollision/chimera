# ADR 0021 — Cross-host peer registry sync (v3.7)

**Status:** Accepted (2026-05-18)
**Builds on:** [ADR 0007](0007-peer-registry.md), [ADR 0011](0011-http-transport.md), [ADR 0014](0014-emergence-protocol-journal.md)

## Context

ADR 0007 made the peer registry filesystem-local. ADR 0014 explicitly
called cross-host registry sync a v3 non-goal. v3.7 closes that gap.

A single-host swarm (multiple Chimeras under one home dir) already works
— they share `~/.chimera/peers/`. A multi-host swarm has no shared
filesystem, and HTTP-reachable Chimeras (ADR 0011) have no way to
discover each other.

## Decision

Pull-based sync over the existing `/healthz` JSON endpoint.

- `/healthz` is extended to include `agent_id` and `capabilities`. The
  status / version / db fields are unchanged.
- New env `CHIMERA_REMOTE_PEERS` — comma-separated base URLs.
- New module `chimera/a2a/remote_sync.py`:
  - `sync_remote_peers(urls=None, *, token=None, timeout=5.0, dir=None)`
    GETs `/healthz` from each URL (carrying `CHIMERA_PEER_TOKEN` as
    bearer if set) and writes a `PeerEntry` with
    `reach = {"transport": "http", "url": "<base>/mcp", "bearer": …}`
    into the local registry. Returns `SyncResult(fetched, added,
    updated, failures)`.
  - `sweep_remote_stale(*, max_age_hours=24, dir=None, now=None)`
    removes only entries whose `reach.transport == "http"` and whose
    `registered_at` is older than the cutoff. Local stdio entries are
    untouched (ADR 0007's pid-based sweep still handles those).
- CLI: `chimera peers sync [--urls ...]` and `chimera peers sweep-remote
  [--max-age-hours N]`.

## Why pull, not push

Push (each Chimera POSTs to a central node) needs a coordinator. Pull
keeps every node self-sufficient and lets operators decide who watches
whom. Cron-equivalent: a systemd timer or k8s CronJob that runs
`chimera peers sync` every minute.

## Non-goals

- No transitive discovery yet — A reads only the URLs it's configured
  for. We don't follow peer's-peers. Add when a use case appears.
- No HTTP push notifications. The 1-minute pull cadence is fine.
- No live drift score in `/healthz` — keeping that endpoint cheap
  matters for k8s liveness probes. Drift remains in the
  `chimera-kfm-state` MCP tool.

## Tests

`tests/test_remote_peer_sync.py` — 6 cases:
- URL parsing (empty, whitespace, trailing slashes)
- `_entry_from_healthz` builds correct reach dict
- happy-path sync writes the registry file
- failures are recorded without writing files
- `sweep_remote_stale` honours `max_age_hours`, ignores stdio entries

Full suite: 441 passing.
