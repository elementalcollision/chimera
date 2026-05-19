# Chimera Scenario

This is the canonical scenario — a self-improving multi-LLM agent (Chimera)
running a cycle-based ACT loop atop a persistent mind/state store with drift detection.

## Architecture

- **Loop**: wake → assess → plan → act → write
- **Drift monitoring**: ghost lexicon + behavioral footprint + semantic drift instruments
- **Ladder**: model fallback tiers (haiku → sonnet → opus)
- **Entities**: state-machine-tracked objects (plans, tasks, agents)
- **Trust tiers**: T0 (locked), T1 (supervised), T2 (unlocked)

## Current State

- Cycle 2, trust tier T0 (locked)
- Plan: bootstrapped, STABLE
- Wiki: empty — being seeded now
- Drift: clean (composite 0.0)
