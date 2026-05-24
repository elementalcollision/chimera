# ADR 0133 — Dialectic API (Phase 3 / item #2)

**Status**: Accepted (2026-05-24)

**Relationship**: Phase 3 item #2 from [ADR 0123](./0123-honcho-inspired-enhancements.md): *"Dialectic API pattern — LLM-queryable peer-model surface."* Consumes the peer cards from [ADR 0128–0131](./0128-peer-cards.md) and, when present, the observer/observed beliefs from [ADR 0132](./0132-observer-observed-beliefs.md).

## Context

Honcho's distinguishing synchronous API is the **Dialectic agent**: a peer can ask a natural-language question about the representation graph and get a grounded answer back. Chimera now has the inputs that make this useful:

- **Peer cards** (`mind/peers/<peer>.md`) — deterministic + optionally narrated per-peer summary.
- **Peer-trust journal** — last N ALLOW/DEGRADE/REFUSE decisions, with reasons.
- **Peer-belief journal** (ADR 0132, optional) — observer/observed belief labels derived from KFM.
- **Live KFM** — opt-in network fetch for the most-current snapshot.

The missing piece is the **read-side surface**: a way for operators and federated peers to query the assembled state in natural language. That's what this ADR ships.

## Design variables (locked via interactive design pass)

| Variable | Choice |
|---|---|
| **Surfaces** | CLI verb (`chimera peers ask`) **and** MCP tool (`chimera-ask`) |
| **Context sources** | Peer card · peer-trust journal · peer-beliefs JSONL (defensive import) · live KFM (opt-in) |
| **Answer shape** | Plain prose paragraph (≤120 words; trimmed at 140 with slack) |
| **Unknown peer** | Stub answer with explicit "no recorded information" framing |

## Decision

### Core module: `chimera/a2a/dialectic.py`

- **`DialecticContext`** dataclass — bundles peer name, peer card markdown, recent decisions, beliefs, optional KFM snapshot, and a `sources_used` provenance list.
- **`gather_dialectic_context(peer_name, *, mind_dir, recent_decisions_n=5)`** — sync reader. Reads the peer card (path-sanitised against `../etc/passwd`), peer-trust journal (newest-first, capped), and **defensively** the peer-beliefs JSONL (works whether or not ADR 0132 has landed on main). KFM fetch is **not** in this function — the caller decides whether to pay the network cost.
- **`build_dialectic_prompt(ctx, question)`** — renders the dialectic template, or the "no recorded information" stub when `ctx.is_empty()`. The stub framing instructs the LLM to be honest about the absence of data rather than confabulate.
- **`trim_answer(text, *, word_cap=140)`** — strips markdown fences and caps at ~140 words. Mirrors the peer-card narrative trimmer (ADR 0130).

The module is **provider-agnostic** — no LLM calls live inside it. Same discipline as the deriver (ADR 0124) and the peer-card narrative helpers (ADR 0130). Callers run the provider.

### MCP tool: `chimera-ask` (`chimera/server/dialectic_tool.py`)

- Always-exposed peer tool (joins identity + KFM in the always-on set).
- Schema: `peer_name`, `question` (both required).
- Handler **returns the assembled prompt** as JSON, **not an LLM answer**. The peer makes its own LLM call against the prompt with its own provider budget. This decision keeps the federation surface free of model-selection concerns and prevents one Chimera from burning another's cost cap on an unbounded inbound query.
- Response shape: `{peer_name, question, prompt, sources_used, is_empty_context}`.

### CLI verb: `chimera peers ask <peer> "<question>"`

- Attaches to the existing `peers` parent verb (alongside `list`, `forget`, `sweep`, `sync`, `kfm`, `cards`). Last sibling on the namespace — closes the slot reserved in [ADR 0131](./0131-peers-cli-verb.md).
- Flags:
  - `--prompt-only` — print the prompt; no LLM call. Debug aid.
  - `--mind-dir` — override `CHIMERA_MIND_DIR` for this call.
  - `--json` — emit `{peer_name, question, answer, sources_used, is_empty_context}`.
- Default behaviour: gather context, build prompt, call sonnet-tier via the local ACT provider stack, print the trimmed answer.
- **No providers configured** → prints a "no providers configured" placeholder answer (rather than failing) so the verb is testable on stripped-down installations.

## Why the MCP tool returns the prompt, not the answer

Two reasons:

1. **Cost containment.** If the MCP tool ran the LLM, an inbound peer query could trigger unbounded sonnet calls on our side, bypassing our per-cycle / rolling-hour caps. Returning the prompt makes the caller pay for the call.
2. **Trust separation.** The caller chooses the model, the system prompt overlay, and the policy that decides how to use the answer. Our job is to give them honest grounding.

The operator CLI verb is different: an operator's invocation is implicitly authorised to spend our cost cap, so calling the LLM locally is appropriate.

## Consequences

### Positive

- Operators can interrogate the peer plane in natural language without learning the journal layouts.
- Federated peers get a Honcho-faithful dialectic surface they can compose with their own reasoning tier.
- The dialectic prompt is a single template that future Phase 4 work (eval harness, dashboard surface) can call into directly.
- Defensive imports mean the dialectic API works today against the peer-card + trust-journal substrate; the moment ADR 0132 lands on main, belief grounding turns on automatically.

### Negative

- Two surfaces (CLI + MCP) mean two test paths. Acceptable: the heavy lifting is in `chimera/a2a/dialectic.py`, which both consume.
- The MCP-tool-returns-prompt design is conceptually unusual (most tools return the *answer*). The schema description and ADR call it out explicitly to head off operator surprise.

## Out of scope (this PR)

- The MCP tool actually invoking an LLM on the callee side. Always returns the prompt; the locked design + ADR explain why.
- Async-batched KFM fetch when answering across multiple peers. Single-peer flow only.
- Question history / dialogue memory — every `ask` is independent. Future ADR can layer on per-session state if useful.
- A dashboard widget that surfaces `peers ask` results. The CLI / MCP outputs are the inspection surfaces today.

## References

- [ADR 0123 — Honcho-inspired enhancements roadmap](./0123-honcho-inspired-enhancements.md) — Phase 3 anchor.
- [ADR 0128 — Peer Cards](./0128-peer-cards.md) / [ADR 0130 — narrative](./0130-peer-card-narrative.md) / [ADR 0131 — CLI verb](./0131-peers-cli-verb.md) — sibling surface conventions.
- [ADR 0132 — Observer/observed beliefs](./0132-observer-observed-beliefs.md) — optional belief source (defensive import).
- [ADR 0124 — Deriver-style extraction](./0124-deriver-style-extraction.md) — provider-agnostic module pattern reused here.
- [`chimera/a2a/dialectic.py`](../../chimera/a2a/dialectic.py), [`chimera/server/dialectic_tool.py`](../../chimera/server/dialectic_tool.py), [`chimera/cli.py`](../../chimera/cli.py) — implementation.
