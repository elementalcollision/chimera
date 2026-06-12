# ADR 0179 — First default-ON flag + registry-default flag reads

**Status:** Accepted (2026-06-12)

## Context

The six 2026-06-08 insertions (ADR 0167–0172) and the federation work around
them (ADR 0174) all shipped **default-OFF** and are now certified on live-fire
evidence (the 2026-06-10/06-12 certification rounds). The natural next step in
maturing them is to begin **graduating the safest to default-ON**.

Two things blocked even the safest graduation:

1. **`flag_enabled` ignored the registry default.** Every bool flag declares a
   `default` in `chimera/config.py`'s `REGISTRY` (ADR 0176), but
   `flag_enabled` read `source.get(name, "")` — hardcoding off-when-unset and
   making the declared `default` documentation-only. A default-ON flag was
   therefore *impossible to express*.
2. **No graduation had a risk-ranked first candidate.** Flipping a hot-path
   behavioural flag (peer selection, fan-out budget, reheat, Boltzmann) on by
   default is a real behaviour change that wants soak evidence in a keyed
   environment. The right first flip is the one with **zero hot-path effect**.

`CHIMERA_FEDERATION_METRICS` (ADR 0168) is exactly that: pure observability. ON,
it adds a `federation` block to the **graph-export snapshot** (an offline CLI
artifact the dashboard reads); it touches no loop phase, no dispatch, no
provider call, no cost. It is also the most thoroughly certified of the batch —
local model-backed-peer exercise (round 3), hand-verified percolation math,
production dashboard build, and a genuine three-process remote-HTTP exercise
(round 4).

## Decision

### 1. `flag_enabled` honours the registry default (the mechanism)

When a bool flag is **unset**, `flag_enabled` now falls back to the flag's
declared `REGISTRY` default instead of assuming off:

```python
raw = source.get(name)
if raw is None:
    spec = REGISTRY.get(name)
    raw = spec.default if (spec is not None and spec.default is not None) else ""
return raw.strip().lower() in TRUTHY
```

- Every flag declared `default=None` (the overwhelming majority) is
  off-when-unset **exactly as before** — byte-identical.
- A flag declared `default="1"` reads True when unset.
- An explicit non-truthy value (`0`/`false`/`off`/empty) always reads False, so
  `CHIMERA_X=0` disables even a default-ON flag — opt-out is always available.

### 2. `CHIMERA_FEDERATION_METRICS` graduates to default-ON

Its `REGISTRY` default flips `None → "1"`. The `chimera graph export` snapshot
now carries the `federation` connectivity block by default; `=0` restores the
prior bare snapshot. This is opt-**out** observability — the inversion of ADR
0168's original "byte-identical until opted in," now that the gauge is certified.

## Tests

- `tests/test_federation_metrics.py` — `test_flag_on_by_default` (unset ⇒ True),
  `test_flag_explicit_disable` (`0`/`false`/`no`/`off`/empty ⇒ False), truthy
  spellings unchanged.
- `tests/test_flag_registry.py` / `tests/test_flag_matrix.py` stay green (71
  across the slice) — the matrix is unaffected because federation metrics is not
  a hot-path flag (not in `HIGH_IMPACT_FLAGS`).
- Verified live: unset ⇒ on, `=0` ⇒ off, and a sample other flag
  (`CHIMERA_PEER_SELECTION`) stays off-when-unset.

## Non-goals

- **Graduating any behavioural flag.** Peer selection, fan-out budget, reheat,
  complexity routing, tool prefilter, and Boltzmann allocation all stay
  default-OFF; flipping any of them is a behaviour change that wants soak
  evidence in a keyed environment and its own ADR. This ADR deliberately moves
  only the zero-hot-path observability flag, and lands the *mechanism* those
  later flips will reuse.
- **Auto-emitting the snapshot.** The flag only governs whether the
  already-invoked `graph export` includes the block; it does not schedule
  exports.

## Why this shape

The mechanism change is the cautious half: it is provably byte-identical for all
171 existing `default=None` flags, so the only behavioural delta in the whole PR
is the single `None → "1"` on the one flag whose ON state cannot affect a task
outcome. That makes this the lowest-risk possible "first default-ON," while
establishing the registry-default-aware read that every future, soak-gated
graduation will use without further plumbing.
