# ADR 0023 — Multi-host demo scenario (v3.10)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0021](0021-cross-host-peer-sync.md), [ADR 0022](0022-emergence-v3.md)

## Context

v3.7 added cross-host peer registry sync, v3.8 added emergence journal
sync. Both shipped with unit tests against a mock transport, but neither
had been exercised end-to-end against a real `chimera serve --http`.

## Decision

New scenario `chimera scenario multi_host` (module
`chimera/scenarios/multi_host_demo.py`):

1. Pick a free localhost port.
2. Seed an emergence observation in an isolated journal dir.
3. Spawn `python -m chimera.cli serve --http --port <port>` with isolated
   `CHIMERA_*` dirs and `CHIMERA_AGENT_ID=chimera-A`.
4. Poll `/healthz` until it answers (up to 12s).
5. From this process, call `sync_remote_peers([base_url])` and
   `sync_remote_emergence([base_url])` writing into a separate B-side
   registry/journal under the same workdir.
6. Assert: `peers_synced == 1`, `peer_a_agent_id` matches, at least one
   emergence record landed under B's `journal/remote/...`.
7. Terminate the subprocess (5s grace, then SIGKILL).

Result is a `MultiHostResult{peer_a_port, peer_a_agent_id, peers_synced,
emergence_records, failures, ok}`.

The scenario uses `state/multi_host_demo/` as its workdir relative to
the configured state_dir parent; safe to delete.

## Why a scenario, not a unit test

Real subprocess + real HTTP + real polling stretches across more
modules than a unit test should. Scenarios are the right home for
"this still works after a wave of refactors" checks.

## Non-goals

- The scenario doesn't verify alignment-ceremony or trust-policy
  behaviour against the live peer — those have unit tests that exercise
  the surfaces directly. The point is the network plumbing.
- No `assert_no_errors` integration here. The scenario is allowed to
  fail loud if env config is wrong; that's a separate concern.

## Tests

Verified by running `chimera scenario multi_host` manually. The scenario
itself is the test; running it from CI is a follow-up.

Full suite: 446 passing.
