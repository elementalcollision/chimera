# ADR 0127 — Wire `ReasoningTier` to ReflectionEngine

**Status**: Accepted (2026-05-24)

**Relationship**: Completes the Phase 2 commitment from [ADR 0123 §"Phase 2"](./0123-honcho-inspired-enhancements.md): "Further `ReasoningTier` wiring as call sites are reviewed."

## Context

[ADR 0123 (Phase 1)](./0123-honcho-inspired-enhancements.md) landed `ReasoningTier` as a typed enum in [`chimera/core/budget.py`](../../chimera/core/budget.py) with no call sites consuming it — the deliberate plan was "future PRs will wire it to model selection." Six PRs later it's still unwired; callers continue to pass literal tier strings (`"haiku"`, `"sonnet"`, `"opus"`) into engines and providers.

The right time to wire it is **now, on one call site**, so that:

1. The contract — how a `ReasoningTier` resolves to a legacy tier string — is concretely visible and testable.
2. Future call sites get a reference implementation to copy.
3. The enum becomes more than a documentation token in `budget.py`.

## Decision

Add two pieces:

1. **`tier_for_reasoning(reasoning_tier, *, default="sonnet") -> str`** in [`chimera/core/budget.py`](../../chimera/core/budget.py) — pure helper mapping `ReasoningTier` to the legacy tier string consumed by `chimera.providers.tiers.select_rung`:

   | `ReasoningTier` | Resolves to |
   |---|---|
   | `None` (no opt-in)   | `default` (caller's literal string) |
   | `MINIMAL`            | `"haiku"` |
   | `NORMAL`             | `"sonnet"` |
   | `DEEP`               | `"opus"` |
   | `MAX`                | `"opus"` (panel selection lives at a different layer; see ADR 0107) |

2. **`ReflectionEngine`** accepts a new keyword argument `reasoning_tier: ReasoningTier | None = None`. When supplied, it **overrides** the literal `tier=` argument via `tier_for_reasoning`. When omitted, every existing caller's behavior is preserved exactly (the default literal `tier="sonnet"` continues to apply).

**No other call sites change in this PR.** Witness, dialectic, and discovery/curiosity engines remain on literal tier strings until a follow-up chip migrates them. Mirroring the Phase 1 plan: "Wire ONE call site as a proof of life. NO refactor of all call sites."

## Why `MAX` collapses to `opus` here

The original enum table called `MAX` "cross-provider witness panel (existing v4.110+)." But panel behavior is an *assembly* decision — multiple providers, voting rule, charter anchoring — selected at the `build_witness_panel` layer (ADR 0107), not at single-call routing. Mapping `MAX` to `"opus"` at the single-call layer makes the helper safe for every call site without the helper having to know about panels. Call sites that want panel behavior continue to call into `chimera/core/witness_panel.py` directly; they can use `ReasoningTier.MAX` as a flag for that branching independently.

## Consequences

### Positive

- The `ReasoningTier` enum now has a documented, tested resolution path. Future call sites can copy the pattern in five lines.
- Backward-compatible by construction: `reasoning_tier=None` → `_tier` literally equals whatever the caller passed in `tier=`.
- The mapping table is in one place — future tier-ladder changes (e.g. when haiku-4.5 ships) touch one dict.

### Negative

- One more constructor argument on `ReflectionEngine`. Mitigated by being keyword-only and defaulting to `None`.
- Adds a `chimera.core.budget` import to `chimera/engines/reflection.py`, increasing engine→core coupling marginally. Acceptable — the engine already imports providers/tiers which are core-shaped.

## Out of scope (this PR)

- Wiring `ReasoningTier` to `DiscoveryEngine`, `CuriosityEngine`, witness, or dialectic-style call sites — each is a separate small chip.
- Changing the default `ReasoningTier` for any caller (still `None` everywhere).
- Per-tier model-id overrides (e.g. routing `MINIMAL` to a specific deepseek-flash rung). The mapping stays at the *tier-string* layer.
- Wiring `ReasoningTier` to the cost-estimate or cycle-cap machinery — those already key off the resolved tier string.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 2 commitment.
- [ADR 0107 — Cross-provider witness panel](./0107-cross-provider-witness-panel-for-code-review.md) — why `MAX` doesn't dispatch a panel here.
- [`chimera/core/budget.py`](../../chimera/core/budget.py) — `ReasoningTier`, `tier_for_reasoning`.
- [`chimera/engines/reflection.py`](../../chimera/engines/reflection.py) — first consumer.
