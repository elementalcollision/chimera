# ADR 0180 — Second default-ON flag: CHIMERA_ENTROPY_SIGNALS

**Status:** Accepted (2026-06-12)

## Context

ADR 0179 built the graduation mechanism (`flag_enabled` honours the
registry `default`) and flipped the one zero-risk flag
(`CHIMERA_FEDERATION_METRICS`). The cloud handoff
([post-merge-validation-2026-06-12.md](../../mind/handoff/post-merge-validation-2026-06-12.md)
§3) ranked `CHIMERA_ENTROPY_SIGNALS` (ADR 0170) as the next rung —
observability that is *loop-wired* (unlike federation metrics' offline
snapshot) and therefore wanted live latency/log-noise evidence from a
keyed environment before flipping.

What ON does (`loop.py` `_phase_act` tail): one Shannon-entropy
computation over the cycle's tool-call names (a `collections.Counter`
over ≤ tens of strings), two extra keys in the act phase's `details`
dict (`tool_entropy`, `tool_calls`), and one phase-log line. No dispatch
change, no provider call, no cost. Low entropy is the designed
degenerate-loop precursor signal — fixation on one tool becomes visible
cycles before the exact-repeat detector fires.

## Evidence (2026-06-12 keyed campaign)

From [routing-soak-campaign-2026-06-12.md](../../mind/research/routing-soak-campaign-2026-06-12.md):

- **ON (Cell A, all-flags envelope):** emission verified live in the
  activity log — `{"tool_entropy": 0.0, "tool_calls": 15}` at cycle 146;
  H=0.0 over a shell-only distribution is mathematically correct and is
  precisely the fixation signal the ADR wants surfaced. No measurable
  latency contribution (the cells' wall-clock difference is attributable
  to a 600 s watchdog fire + model-peer consults, both flag-orthogonal).
  Log noise: exactly one line per cycle.
- **OFF (Cell B, baseline):** act details byte-identical to the
  pre-ADR-0170 shape (`{"tasks", "completed", "api_calls"}`) — the
  opt-out contract holds live, not just in tests.

## Decision

Flip the registry default: `CHIMERA_ENTROPY_SIGNALS` `None → "1"` in
`chimera/config.py`. Per the ADR 0179 contract, any explicit non-truthy
value (`0`/`false`/`off`/empty) still disables.

Tests updated to the graduation pattern (mirroring #291):

- `test_entropy_signals.py`: `test_flag_on_by_default` +
  `test_flag_explicit_disable` (parametrized over `0/false/off/empty`).
- `test_entropy_signals_wiring.py`: `test_flag_unset_emits_by_default`
  (loop-level emission with unset env) and the byte-identical assertion
  moved to the explicit-disable path
  (`test_flag_disabled_is_byte_identical`).

## Consequences

- Every cycle now carries the tool-entropy signal by default — operators
  and the dashboard get the degenerate-loop precursor for free; the
  emission cost is one Counter + one log line.
- Anyone parsing the act `details` dict gains two keys; the prior keys
  are unchanged (asserted by the wiring tests).
- The graduation ladder advances: next rungs (`COMPLEXITY_ROUTING` /
  `TOOL_PREFILTER`) stay gated on cost-delta evidence; the behavioural
  trio on deliverable-landing soak evidence with a gate-visible driver
  (campaign Finding 1); the peer pair on multi-peer default topology.

## Falsification / revisit triggers

- If per-cycle log volume becomes an operational complaint, demote the
  phase-log line to DEBUG while keeping the `details` keys (the
  dashboard's data path) — don't re-flip the default.
- If a downstream consumer breaks on the new `details` keys, that's a
  consumer bug by the wiring tests' contract, but revisit if it recurs.
