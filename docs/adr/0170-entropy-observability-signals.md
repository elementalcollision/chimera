# ADR 0170 — Entropy observability signals (v4.120)

**Status:** Proposed (2026-06-08)

## Context

Several signals Chimera already half-measures *are* entropies, but they are
read today only through exact-match thresholds (the `act.py` exact-repeat
degenerate-loop detector; `dedup.py`'s fingerprint/cluster collision; the
composite drift's stagnation term). The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
(§3d, ranked #5, "cheapest wins") observes that *naming* these entropies turns
binary thresholds into continuous diagnostics that fire **earlier**:

- **Tool-use entropy** — low H(tool distribution) is fixation, a degenerate-loop
  *precursor* visible before any exact repeat.
- **Proposal diversity** — cluster entropy over `dedup.cluster_key` flags a
  redundant batch before a single pair is an exact fingerprint collision.
- **Stagnation** — the *falling* entropy of the KFM-transition distribution is
  the principled form of the drift score's stagnation component.

## Decision

A pure entropy primitive plus the named signals, with a flag that gates
emission (the functions themselves are always computable).

### Code

- `chimera/core/entropy_signals.py` — new module:
  - `entropy_signals_enabled()` — honours `CHIMERA_ENTROPY_SIGNALS` (default
    off; same parsing shape as `peer_selection_enabled`, ADR 0167).
  - `shannon_entropy(counts)` — entropy in **bits**; scale-invariant, ignores
    non-positive counts, 0.0 for empty/singleton.
  - `normalized_entropy(counts)` — scaled to `[0, 1]` by `log2(k)`; 1.0 =
    uniform (max diversity), 0.0 = fixation.
  - `entropy_of_labels(labels)` — normalized entropy over a categorical
    sequence.
  - `tool_use_entropy(tool_names)` — fixation gauge over a cycle's tool calls.
  - `proposal_diversity(texts)` — cluster entropy via `dedup.cluster_key`
    (fingerprint fallback); low ⇒ redundant batch.
  - `transition_entropy(transitions)` — entropy of `(from, to)` KFM/activity
    transitions; a value that falls over windows is stagnation.

### CLI / dashboard

None in this ADR. The primitives are the deliverable; the wiring seams (a
tool-use-entropy series beside the existing "tool fan-out" dashboard plot, a
proposal-diversity check in the generate→dedup flow, a transition-entropy term
in the drift composite) consume these functions and are gated by
`CHIMERA_ENTROPY_SIGNALS`, so behaviour is byte-identical until opted in.

## Tests

`tests/test_entropy_signals.py` — 20 cases: flag parsing; `shannon_entropy`
empty/singleton/uniform-2 = 1 bit / uniform-4 = 2 bits / scale-invariance and
non-positive filtering; `normalized_entropy` uniform = 1, fixation low,
singleton = 0; `entropy_of_labels`; `tool_use_entropy` fixation < diverse and
single-tool/empty = 0; `proposal_diversity` redundant-batch < diverse and
distinct-cluster = 1.0; `transition_entropy` stuck self-loop < varied (and = 0).

## Non-goals

- **Replacing the exact-match detectors.** Entropy signals are *precursors* and
  diagnostics; the degenerate-loop abort, dedup, and drift lockdown stay
  authoritative. Entropy widens the warning window, it doesn't gate.
- **The full free-energy / active-inference rebuild** (research §3c). The cheap
  80% is naming these entropies; an EFE scheduler for the engines is a separate,
  heavier effort.
- **Dashboard plumbing.** Deferred to a follow-up that adds the tool-use-entropy
  series to the fan-out widget once a per-call tool-name source is wired.

## Why this shape

Keeping the primitives pure and always-computable (the `complexity_floor_tier`
discipline of ADR 0166) means the entropies can be unit-tested and previewed
without touching the hot loop, and each wiring site opts in independently. The
proposal-diversity signal deliberately reuses `dedup.cluster_key` so the
entropy and the existing dedup speak the *same* notion of "same intent" — the
continuous signal and the binary collision stay consistent.
