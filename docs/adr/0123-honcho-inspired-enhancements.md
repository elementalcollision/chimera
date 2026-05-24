# ADR 0123 — Honcho-inspired enhancements roadmap

**Status**: Accepted (2026-05-24, Phase 1 only)

## Context

The R&D evaluation [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md) surveyed Plastic Labs' [Honcho](https://github.com/plastic-labs/honcho) — an AGPL-3.0 "memory infrastructure for agents" built around **dialectic reasoning + Theory-of-Mind**. The evaluator's recommendation was **inspire, don't integrate**: port specific concepts natively rather than depend on Honcho's Postgres + pgvector + Redis + FastAPI stack, which would invert Chimera's "single binary + SQLite" deployment posture.

The operator endorsed the recommendation and surfaced eight net-new additions worth considering. This ADR records the phased adoption plan and ships Phase 1.

Honcho's distinguishing abstractions (Workspace, Peer, Session, Deriver, Dialectic agent, Peer Cards, Representations, Reasoning tiers, hybrid BM25+vector search, LongMemEval/LoCoMo benchmarks) overlap partially with Chimera's existing memory, federation, trust, witness, and reflection subsystems — see the overlap matrix in the evaluation doc.

## Decision

Adopt eight Honcho-inspired enhancements as a phased workstream, ordered by effort × value. **Phase 1 ships in this PR**; later phases land as separate chips.

### Phase 1 — trivial wins (THIS PR)

- **#5 Reasoning tiers** — `ReasoningTier` enum (`MINIMAL | NORMAL | DEEP | MAX`) in [`chimera/core/budget.py`](../../chimera/core/budget.py). Default `NORMAL`; backward-compatible. Future PRs wire tiers to model selection at dialectic / witness / reflection call sites.
- **#7 Token-aware `Context.to_openai()` builder** — small `Context` dataclass with system + messages + `max_tokens`, materializing an `openai.chat.completions.create`-compatible payload that truncates middle messages first under budget. Uses `tiktoken` opportunistically; falls back to a 4-chars-per-token heuristic. **No new dependency.**

Both additions are pure utility code — no existing call site changes behavior.

### Phase 2 — follow-up chips (small effort, design-light)

- **#3 Deriver-style structured-output extraction** — single LLM call per batch returning typed conclusions (replacing parts of the agentic Reflection-engine loop). Effort: trivial-to-moderate.
- Further `ReasoningTier` wiring as call sites are reviewed.

### Phase 3 — per-chip operator decisions (moderate effort, design-heavy)

- **#1 Observer/observed representation pairs** — symmetric "what does Chimera believe about peer X vs. what peer X believes about Chimera"; new edge type in `chimera/memory/graph.py` plus cross-agent belief-state in `chimera/federation/`.
- **#2 Dialectic API pattern** — LLM-queryable peer-model surface as a new MCP tool in `chimera/transport/`.
- **#4 Peer Cards with periodic consolidation** — per-peer postmortem refreshed on schedule; slots into the ROTATE phase.

### Phase 4 — research-first (substantial effort, blocked on evaluation)

- **#6 Hybrid BM25 + vector search** over peer-scoped collections. Needs a `sqlite-vec` vs. `LanceDB` evaluation first — **NOT pgvector**. Lands in `chimera/wiki_search.py`.
- **#8 LongMemEval / LoCoMo benchmarks** — **integrate** the eval harness (run their evals; do not port). Scores Chimera's memory subsystem against published baselines.

## Non-criteria (explicit deprioritizations)

- **Honcho's Workspace multi-tenancy** — Chimera is single-agent scope by ADR 0005; multi-tenancy adds operational complexity without benefit.
- **Redis queue / background deriver worker** — Chimera's eight-phase loop is the work scheduler; introducing Redis would invert the deployment story.
- **AGPL-3.0 dependency adoption** — porting concepts is licence-clean; depending on the Honcho binary is not.
- **pgvector** — out of scope under "no Postgres".

## Consequences

### Positive

- Reasoning tiers formalise a cost/quality knob that's currently implicit in tier-promotion logic; future PRs can specialise model selection per tier without churning call signatures.
- `Context.to_openai()` gives a single place to evolve prompt-assembly policy (truncation, token estimation, payload shaping) instead of duplicating ad-hoc string-building at each provider call site.
- The phased plan makes Honcho's stronger ideas (observer/observed, dialectic API, peer cards) explicitly cherry-pickable without committing to the framework.

### Negative

- Two new public symbols (`ReasoningTier`, `Context`) add surface area. Mitigated by both having clear defaults and being optional.
- `Context.to_openai()` is unwired to existing call sites in this PR; risk of bit-rot if Phase 2 is dropped. Mitigated by tests asserting the contract and by terminology alignment with the R&D doc for traceability.

## Out of scope (this PR)

- Wiring all existing prompt-assembly call sites to `Context.to_openai()` — follow-up.
- Switching the `ReasoningTier` default from `NORMAL` to anything else.
- Actually depending on `sqlite-vec`, `LanceDB`, or `tiktoken` (the last is used opportunistically only).
- Items #1, #2, #3, #4, #6, #8 — each gets its own chip.

## References

- [`mind/research/honcho-evaluation-2026-05-24.md`](../../mind/research/honcho-evaluation-2026-05-24.md) — R&D evaluation that surfaced the eight items.
- [ADR 0002 — Memory strategy](./0002-memory-strategy.md) — why Chimera owns its memory plane.
- [ADR 0005 — Multi-agent architecture](./0005-multi-agent-architecture.md) — single-agent scope decision.
- [ADR 0107 — Cross-provider witness panel](./0107-cross-provider-witness-panel-for-code-review.md) — existing analog of `ReasoningTier.MAX`.
