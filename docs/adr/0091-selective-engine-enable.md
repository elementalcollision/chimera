# ADR 0091 — Selective per-engine enable (v4.72)

**Status:** Accepted (2026-05-20)

## Context

`mind/postmortems/engine-telemetry-2026-05-20.md` §P5 noted:

> Replace `CHIMERA_ENGINES_ENABLED` with per-engine flags
> (`CHIMERA_DISCOVERY_ENABLED=1` etc.), all default off post-v4.54
> (ADR 0073 §4 already shipped the global default-off; this just
> makes the opt-in granular).

The current scheduler has a single coarse switch
(`CHIMERA_ENGINES_ENABLED=0/1`) that kills all three engines
together. In practice an operator wants to silence one — typically
Curiosity, which has the most expensive failure mode (a research
loop on a thin topic) — while keeping Discovery and Reflection
running. There's no clean way to express that today.

The post-mortem also proposed wiring engines to read prior chronicle
content via FTS5 (chronicle-as-input). That half is deferred to a
follow-up: it requires engine prompt rewrites and is where quality
regressions hide. This ADR ships only the mechanical, safe half.

## Decision

### New module-level helpers in `chimera/engines/scheduler.py`

```python
def _engine_individually_enabled(name: EngineName) -> bool:
    key = f"CHIMERA_{name.upper()}_ENABLED"
    return os.environ.get(key, "1") not in ("0", "false", "False")


def engine_enable_snapshot() -> dict[str, bool]:
    return {n: _engine_individually_enabled(n)
            for n in ("discovery", "curiosity", "reflection")}
```

### Wire into `pick_due`

After picking the time-window candidate, consult
`_engine_individually_enabled(candidate)`. If the individual flag is
off, return `None`. Order with the existing logic:

1. `force` bypasses everything (manual operator override, unchanged)
2. Global `CHIMERA_ENGINES_ENABLED=0` → None (unchanged kill)
3. Time-window selects candidate
4. **New:** per-engine flag — return None if off
5. Per-day idempotency check

The per-engine flag is the *opt-out* layer. Defaults all-on, so the
v1.1 / v4.x behaviour is unchanged when the operator sets nothing.

### Environment knobs

| Env | Default | Meaning |
|---|---|---|
| `CHIMERA_ENGINES_ENABLED` | `1` | global kill (unchanged) |
| `CHIMERA_DISCOVERY_ENABLED` | `1` | per-engine opt-out |
| `CHIMERA_CURIOSITY_ENABLED` | `1` | per-engine opt-out |
| `CHIMERA_REFLECTION_ENABLED` | `1` | per-engine opt-out |

## Tests

`tests/test_engine_selective_enable.py` — 9 tests covering:

- `engine_enable_snapshot()` default-on and reads per-engine env
- Each window (discovery/curiosity/reflection) skipped when its
  flag is `0` while the others continue to fire
- Global kill overrides per-engine on
- `force=...` bypasses the per-engine flag (operator escape hatch)
- All-defaults sanity check (no regression on v1.1 behaviour)

Full suite: 779 passing (was 770, +9 new).

## Non-goals

- **No CLI verb.** The four env vars are operator-set in
  `chimera.env` / shell; a `chimera engines enable/disable <name>`
  verb is mechanical to add but adds surface area. The
  `engine_enable_snapshot()` helper is here for the dashboard to
  read.
- **No chronicle-as-input.** The other half of P5 — engines reading
  prior chronicle via FTS5 — requires prompt rewrites and benefits
  from a separate change with its own quality-regression test
  scaffold. Deferred to a follow-up. With v4.71 proposer-scoring
  in place, a chronicle-input regression will be caught: a
  proposer that flips to degraded after the prompt rewrite is the
  signal we want.
- **No dashboard widget.** Adding the snapshot to the
  control-plane API is one line; the widget design is its own
  follow-up.

## Why this shape

Why env vars instead of DB rows? Because the operator's normal
workflow for tuning engine behaviour is editing `chimera.env`
(matches ADR 0073's pattern for `CHIMERA_PLAN_ENGINE_ENABLED=0`).
Adding a DB row would split engine config between two stores.

Why default-on per-engine while v4.54 shipped global default-off?
Because `CHIMERA_ENGINES_ENABLED=0` (v4.54 default) already silences
everything. The per-engine flag is a *finer-grained re-enable* —
when the operator turns the global switch on, they get all three by
default. To run only Reflection: `ENGINES_ENABLED=1` plus
`DISCOVERY_ENABLED=0` and `CURIOSITY_ENABLED=0`.

Why does `force` bypass the per-engine flag? Because `force` is an
explicit operator override ("run discovery right now") and per-engine
flags shouldn't second-guess that. The acceptance criterion: any
manual `chimera run --engine discovery` must execute even if the
ambient config has discovery disabled.
