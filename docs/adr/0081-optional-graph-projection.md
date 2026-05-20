# ADR 0081 — Graph projection is now opt-in (v4.62)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0015](./0015-graph-store.md) (LadybugDB/Kuzu graph store)
shipped the graph projection at v2.10 as a default-on, core
dependency. The 2026-05-20 ADR-revisit in
`mind/overnight/adr-revisits.md` named the regret cleanly:

> Honestly? Probably not, or at least not as a core dependency so
> early. LadybugDB (née Kuzu) is impressive tech […]. But the gap
> between "six nice-to-have graph queries" and "must ship a
> Ladybug container volume" is wider than this ADR admits. […]
> The CLI surface (`chimera graph init`, `rebuild`, `query`) is
> nice but got used maybe twice outside testing. Today I'd make
> the graph an **optional** projection.

The graph powers a small number of dashboard widgets (skill graph,
KFM entity graph) via the JSON snapshot at
`state/chimera.graph.snapshot.json` — but ~95% of dashboard data
flows through SQLite directly. The Kuzu projection's main cost was
the housekeeping auto-refresh: a ~200ms hit every cycle, plus the
v4.43 fingerprint-sidecar workaround for newer Kuzu's single-file
DB layout on macOS. Operators rarely used the Cypher query surface
outside testing.

Per ADR 0015's revisit recommendation: keep the graph as an
optional projection (`chimera graph rebuild` is one explicit
invocation away when you want Cypher), default everything else
to the SQLite-recursive-CTE path the dashboard already uses.

## Decision

### 1. New gate: `graph_projection_enabled()` in `chimera/core/loop.py`

```python
def graph_projection_enabled() -> bool:
    enabled = os.environ.get("CHIMERA_GRAPH_ENABLED", "").lower() in (
        "1", "true", "yes",
    )
    forced_off = os.environ.get(
        "CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", ""
    ).lower() in ("1", "true", "yes")
    return enabled and not forced_off
```

Default: **OFF**. Opt in:

```bash
export CHIMERA_GRAPH_ENABLED=1
```

Legacy `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED=1` still wins — back-compat
for operators who pinned that var to disable updates when they were
default-on. Their behavior is unchanged.

### 2. Housekeeping respects the gate

`chimera/core/loop.py:_phase_housekeeping` calls
`graph_projection_enabled()` instead of the previous
"unless-disabled" check. When disabled, the auto-refresh skips
entirely — no Kuzu import, no file I/O, no fingerprint computation.

### 3. CLI verbs still work — they're explicit

`chimera graph init/rebuild/query/snapshot/stress` are always
available regardless of the gate. They're explicit operator
invocations; the gate only controls the housekeeping auto-refresh.

When the operator runs `chimera graph init` or `chimera graph
rebuild` while the gate is off, a one-line hint warns them their
hand-rebuilt graph will go stale next cycle unless they enable
the gate.

### 4. Migration story

Operators upgrading from v4.61 → v4.62 with no env changes will
see:
- Housekeeping stops refreshing `state/chimera.graph` each cycle.
- The dashboard's skill-graph and KFM-graph widgets show
  whatever state was last snapshot'd via the CLI.
- All other widgets, all CLI verbs except `chimera graph rebuild`,
  and all in-loop SQL queries continue working unchanged.

To restore prior behavior: `export CHIMERA_GRAPH_ENABLED=1`.

## Tests

`tests/test_graph_optional.py` — 7 tests pinning the gate:

- Default → False (no env)
- Explicit `=0` → False
- Truthy values (`1`/`true`/`yes`, case-insensitive) → True
- Falsy/garbage values → False
- Legacy `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED=1` alone does NOT
  enable
- Legacy disable still wins over new enable
- Legacy `=0` with new `=1` → True (enabled, not forced off)

Full suite after v4.62: 662 passing (was 655, +7 new).

## Non-goals

- **Not removing the graph projection.** ADR 0015 still applies for
  operators who want Cypher expressiveness. The cost of keeping the
  code paths is minimal; flipping the default is the lever.
- **Not changing the dashboard's graph widgets.** They read the JSON
  snapshot; when stale they show stale data, which is the honest
  semantic. A "graph projection: stale (last refreshed 2 cycles
  ago)" warning is a natural follow-up but not needed for this ADR.
- **Not building SQLite-CTE fallbacks for the few queries the graph
  uniquely powers.** That's a separate refactor: the
  skill-dependency adjacency and the wiki cross-reference graph
  could be JSON adjacency lists read at boot. Filed as future
  work; the gate flip is the immediate action.
- **Not migrating away from Kuzu.** Same as above — the projection
  stays. We're just making it opt-in.

## Why this shape

Why a new env var instead of repurposing the legacy one? Because
the legacy variable's name is `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED`
— a *disable* var. Flipping its default to also mean "enable when
unset" would confuse anyone reading it. Adding
`CHIMERA_GRAPH_ENABLED` as the affirmative gate, while honoring the
legacy disable, is the operator-respectful path.

Why default off instead of "default on but easier to disable"?
Because the ADR-0015 revisit was explicit: the projection got
"used maybe twice outside testing." If it's truly off the critical
path for 95% of operators, default off matches reality. Operators
who use Cypher actively set one env var and get it back. Operators
who don't pay nothing.

Why keep the CLI verbs always available? Because the operator who
explicitly types `chimera graph rebuild` IS asking for the
projection in that moment. Refusing without an enable flag would
be paternalistic. The hint message is enough: it tells them the
projection will go stale unless they also turn on auto-refresh.
