# ADR 0018 — Operational hardening (v3.3)

**Status:** Accepted (2026-05-18)

## Context

Chimera now has 50+ modules, a derived graph store, a peer-trust journal,
and a dashboard. Before another wave of features lands, we want a small,
non-invasive set of hooks that make production-shaped deployments legible:
JSON logs, a structured health probe, and phase-time accounting.

## Decision

### `chimera.core.observability`

- `configure_logging(json_mode=None, level=None)` — idempotently installs
  a single stderr handler. JSON output activates when
  `CHIMERA_LOG_JSON=1`. Level via `CHIMERA_LOG_LEVEL` (default `INFO`).
- `phase_timer(name, *, budget_ms=None)` — context manager that records
  wall-clock and emits one log record at exit. DEBUG by default; WARNING
  when elapsed exceeds the budget. Yields a dict so callers can read
  `elapsed_ms` for cycle reports.

The JSON formatter passes through any `extra={…}` fields that are
JSON-serializable, so phase timing carries `{phase, elapsed_ms, budget_ms}`
without bespoke wiring.

### `/healthz` endpoint

`chimera serve --http` now exposes both `/health` (plain text, unchanged)
and `/healthz` (JSON). `/healthz` reads HEARTBEAT.md and runs `SELECT 1`
against `chimera.db`; status downgrades to `degraded` if either fails.
Returned shape:

```json
{
  "status": "ok",
  "version": "3.3.0",
  "cycle": 42,
  "trust_tier": "T2",
  "session_started_at": "2026-…",
  "db": "ok"
}
```

Like `/health`, the new route is exempt from bearer auth — k8s liveness
probes need it reachable without secrets.

## Non-goals

- Loop integration is **not** done in this ADR. `phase_timer` ships as a
  primitive; weaving it into the 8-phase loop is a follow-up so we can
  observe the shape of timing data first.
- No metrics endpoint (Prometheus / OTEL) yet — defer until phase timing
  surfaces a real bottleneck.
- Log shipping is out of scope; stderr-to-JSON is enough for `docker logs`
  / k8s log collectors to consume.

## Tests

`tests/test_observability.py` (4 cases) + a `/healthz` case in
`tests/test_http_transport.py`. Full suite: 420 passing.
