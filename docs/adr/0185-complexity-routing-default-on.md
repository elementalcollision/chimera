# ADR 0185 — Graduate CHIMERA_COMPLEXITY_ROUTING to default-ON

**Status:** Proposed (2026-06-18) — *evidence-gated; the Evidence section is a
placeholder until a keyed flag-OFF/ON soak runs.*

## Context

The pair to ADR 0184. ADR 0180 named `COMPLEXITY_ROUTING` (ADR 0166) a next
graduation rung gated on cost-delta evidence; `chimera cost-delta` now supplies
the verdict.

What ON does (`chimera/core/escalation.py`, `complexity_routing_enabled` /
`complexity_floor_tier`, ADR 0166): a lexical complexity floor lifts the
*starting* tier for multi-step / design / broad-tool-chain tasks the default
tier would under-serve — avoiding a doomed cheap-rung attempt before escalation.

**Cost-delta interpretation differs from 0184.** TOOL_PREFILTER is a pure-cost
reduction; COMPLEXITY_ROUTING *trades cost for quality* — starting higher can
cost MORE per task but should reduce wasted cheap-rung rounds and raise
gate-pass on hard tasks. So the graduation criterion is **not** "treatment
cheaper" alone; it is **cost-delta read together with gate-pass delta**: a
modest cost increase is acceptable iff it buys a real completion/quality gain
(fewer failed rounds, higher gate-pass), and a cost *decrease* (fewer wasted
rounds) at parity quality is an unambiguous win.

## Evidence (keyed flag-OFF/ON soak — TO BE FILLED)

Procedure (keyed env, scheduler off):

1. Run a representative gate-visible spec (ideally a multi-step / "design"
   task that exercises the floor) twice — `CHIMERA_COMPLEXITY_ROUTING=0` then
   `=1` — preserving each `api_calls` DB; record gate result + rounds for each.
2. `chimera cost-delta --baseline <off.db> --treatment <on.db>`.
3. Graduate **iff** ON improves the outcome — either cheaper at parity gate
   quality, OR a modest cost increase that yields a clear gate-pass/round-count
   improvement on the hard task. Record both the cost-delta AND the gate/round
   comparison (cost alone is not sufficient here).

> _Evidence: pending the keyed run. Drop the `cost-delta` verdict + the
> gate/round comparison here, then move Status → Accepted._

## Decision (on evidence)

Flip the registry default: `CHIMERA_COMPLEXITY_ROUTING` `None → "1"` in
`chimera/config.py`. Explicit non-truthy values still disable (ADR 0179).

Test graduation pattern:
- `tests/test_complexity_routing.py`: add a default-ON assertion with the env
  unset (keep the explicit-parsing test).
- `tests/test_flag_graduation_0184_0185.py`: un-skip
  `test_complexity_routing_default_on_after_graduation`.

## Consequences
- Hard/multi-step tasks start at an appropriate tier by default → fewer wasted
  cheap-rung rounds; opt-out via `CHIMERA_COMPLEXITY_ROUTING=0`. Per-task cost
  may rise on those tasks — accepted only because the evidence shows the
  quality/round trade is worth it.

## Falsification / revisit triggers
- If ON raises cost without a matching gate-pass/round improvement, **do not
  graduate** — the floor is mis-tuned, not earning default-on.
- If the floor over-lifts cheap-but-doable tasks (cost up, no quality gain),
  narrow `complexity_floor_tier`'s heuristic before re-attempting.
