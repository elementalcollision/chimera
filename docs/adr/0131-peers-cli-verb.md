# ADR 0131 — `chimera peers cards` CLI Verb (final Phase 3 #4 follow-up)

**Status**: Accepted (2026-05-24)

**Relationship**: Closes the third and final follow-up named in [ADR 0128 §"Follow-ups"](./0128-peer-cards.md): *"`chimera peers cards` CLI verb to consolidate on demand without waiting for ROTATE."*

## Context

[ADR 0128](./0128-peer-cards.md), [ADR 0129](./0129-peer-cards-rotate-wiring.md), and [ADR 0130](./0130-peer-card-narrative.md) shipped the deterministic module, the ROTATE-phase wiring, and the opt-in LLM narrative layer. The remaining gap was operator ergonomics — refreshing peer cards required either a session rotation (slow) or an interactive Python REPL session (clunky).

A CLI verb closes the loop. The locked design (from the interactive pass) put it on `chimera peers cards` so a future `chimera peers ask` (Phase 3 #2 dialectic API) can attach as a sibling subcommand without re-shaping the namespace.

## Decision

Register a **`peers` parent verb** in [`chimera/cli.py`](../../chimera/cli.py) with `cards` as its first child:

```
chimera peers cards [--narrative] [--mind-dir PATH] [--state-dir PATH] [--json]
```

Flags:

- **`--narrative`** — sets `CHIMERA_PEER_CARD_LLM=1` for the call and invokes `ChimeraLoop._enrich_cards_with_narratives` (the same path ROTATE uses). Deterministic-only otherwise; matches the locked design ("Deterministic-only by default; `--narrative` opts in").
- **`--mind-dir`** / **`--state-dir`** — override the env-derived paths for this invocation (useful for ad-hoc consolidations against a specific worktree).
- **`--json`** — emit a machine-readable summary (`{"written", "count", "narrative", "peers"}`) instead of the default human-readable lines.

Implementation: a private `_cmd_peers_cards(args)` helper builds a `ChimeraLoop` (without running a cycle), pulls peer names via `list_peer_chimeras(loop._registry)`, builds the cards via the same `build_self_card` + `build_peer_card` calls as the loop helper, optionally enriches via the existing `_enrich_cards_with_narratives` method, then writes them with `write_peer_card`. No new business logic — the verb is a thin operator-facing front for the existing engine code.

## Why register on the existing `chimera/cli.py` (not a new package)

The locked design picked "new `chimera/cli/peers.py` subcommand", but the existing CLI is a single 2400-line file rather than a package. Refactoring `cli.py` into `chimera/cli/` would touch every existing verb's import path — a refactor larger than this whole peer-cards series. Instead, this PR adds the `peers` parent verb inline in `cli.py` and structures it as a parent verb with subcommands, so future verbs (e.g. `peers ask` for Phase 3 #2) attach naturally as siblings of `cards`. The "module boundary" intent of the locked design is preserved at the verb level even if not at the file level.

## Consequences

### Positive

- Operators can refresh `mind/peers/` on demand without waiting for a session rotation. Critical for debugging and for the eventual `peers ask` workflow.
- `--narrative` exposes the LLM enrichment path without requiring an env-var set. Convenient for ad-hoc inspection.
- The `peers` parent verb gives the dialectic API a natural home: `peers ask <peer> "<question>"` slots in without re-namespacing.
- `--json` makes the verb scriptable from a parent process.

### Negative

- `cli.py` keeps growing. Mitigated by the new code being one parser block + one handler function; if cli.py ever gets refactored to a package, this verb moves cleanly because it has a private helper.
- The verb instantiates a `ChimeraLoop` (with its full trust manager, ACT executor, tool registry) just to consolidate cards. Heavier than strictly needed but consistent with the rotate-time path; future optimisation could carve out a thinner "peer-cards context" helper.

## Out of scope (this PR)

- `chimera peers ask` (dialectic API) — that's Phase 3 #2.
- Refactoring `chimera/cli.py` into a package — out of scope for the locked design's spirit.
- CLI for editing peer cards by hand — markdown editor or `mind/peers/<name>.md` direct edit covers that already.
- Async KFM fetch in the CLI path — same as rotate path; deferred.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 #4 anchor.
- [ADR 0128 — Peer Cards module](./0128-peer-cards.md) — schema + locked design including this CLI verb.
- [ADR 0129 — Wire Peer Cards into `_phase_rotate`](./0129-peer-cards-rotate-wiring.md) — the ROTATE-phase counterpart.
- [ADR 0130 — Peer-Card LLM Narrative Layer](./0130-peer-card-narrative.md) — the `--narrative` flag wires into the same `_enrich_cards_with_narratives` helper.
- [`chimera/cli.py`](../../chimera/cli.py) — `_cmd_peers_cards`, `peers` parser registration.
