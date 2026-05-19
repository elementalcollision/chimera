# ADR 0020 — Boot-time config validator (v3.6)

**Status:** Accepted (2026-05-18)
**Builds on:** [ADR 0018](0018-operational-hardening.md)

## Context

Chimera reads ~20 environment variables. Most have sensible defaults, but
a handful — `CHIMERA_MCP_SERVERS`, `CHIMERA_PEER_TOKENS`, the API keys,
the writable state/mind dirs — fail late and with low-signal errors when
misconfigured. A k8s deployment with malformed `CHIMERA_PEER_TOKENS` JSON
silently accepts every request as anonymous; a missing state directory
surfaces as a sqlite OperationalError mid-cycle.

## Decision

New module `chimera/core/doctor.py`:

- `CheckResult(name, status, message)` — three statuses: `ok`, `warn`,
  `error`.
- `run_checks()` — runs every check; returns a list. Pure side effects
  limited to `mkdir(parents=True, exist_ok=True)` on state/mind dirs
  (those are required to exist, and creating them is the right outcome).
- `assert_no_errors(results=None)` — raises `ConfigError` if any check
  is `error`; logs `WARNING` for each `warn`; otherwise returns the
  results.

Checks shipped in v3.6:
- `state_dir`, `mind_dir` — creatable + writable
- `chimera.db` — opens, executes `SELECT 1`
- `graph: kuzu` — `import kuzu` succeeds (catches stale installs)
- `CHIMERA_MCP_SERVERS` — empty OK, otherwise parses as JSON object
- `CHIMERA_PEER_TOKENS` — empty OK, otherwise parses as JSON object
- `http auth` — warns when neither token env is set
- `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` — warn when unset

### Wiring

- New CLI verb `chimera doctor` runs checks and prints a status line per
  check, exiting non-zero on any `error`.
- `serve_http` and `serve_stdio` call `assert_no_errors()` before
  starting the event loop. Misconfiguration fails loud at boot instead
  of mid-cycle.

## Non-goals

- We do not validate ladder env vars (`CHIMERA_OPUS_PLAN_EVERY_N`, the
  hour-of-day engine envs). They have safe defaults and parsing errors
  surface clearly in current code.
- No live probe against Anthropic / OpenRouter — that's `chimera ping`.
- No re-check during the loop. One-shot preflight is enough.

## Tests

`tests/test_doctor.py` — 8 cases covering the happy path, each warn
scenario, malformed-JSON errors, and `assert_no_errors` propagation.
Full suite: 435 passing.
