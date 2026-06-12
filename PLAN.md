# Chimera — Implementation Plan

> **Status (2026-06-10):** *Historical.* This document captured the
> research-spike-first plan that took Chimera from concept through
> Phase 0–4 into v1.0, then v2.0 (federation), v3.0 (graph-backed
> memory), and v4.0 (post-mortem polish + the v4.x learning loop —
> v4.120 at last update). All phases here are complete; the unchecked
> boxes below are preserved as written, not open work.
>
> **For the live system record**, see:
> - [docs/adr/README.md](docs/adr/README.md) — every architectural
>   decision since Phase 0, 175 ADRs and counting.
> - [README.md](README.md) — current production shape,
>   container + dashboard + CLI surfaces.
>
> This file is preserved as the design narrative.

## Current roadmap (2026-06-10 consolidation review)

The 2026-06-10 codebase review (ADRs 0175/0176) shifted focus from
feature velocity to consolidation. Open items, in order:

- [x] Security hardening: timing-safe bearer auth, subprocess env
  hygiene, atomic trust-state writes, ruff CI gate — ADR 0175.
- [x] Central flag registry + flag-combination test matrix; direct test
  modules for budget/escalation/remediation — ADR 0176.
- [x] Extract act.py guards and cli.py command handlers (pure moves) —
  ADR 0177.
- [x] Wire `config.validate_env()` warnings into loop startup.
- [x] Registry read path (`flag_enabled`/`flag_int`/`flag_float`) +
  first tranche: the 12 ADR 0165–0174 family readers (10 modules).
  Remaining legacy reads migrate opportunistically.
- [x] Word-boundary fix for `remediation._is_commit_task` (xfail retired).
- [x] TLS for the HTTP MCP transport (ADR 0178): fail-closed cert/key
  pair, non-loopback now requires token **and** TLS.
- [~] Evals (LongMemEval/LoCoMo) as a gated nightly. Gate built +
  CI-tested (`chimera evals summarize`, ADR 0181); nightly workflow
  is a manual-dispatch template. **Go-live needs 4 operator decisions:**
  grader choice, CI secrets, dataset hosting, budget/threshold.
- [x] Post-merge validation handoff (2026-06-12): all-flags envelope A/B
  live-validated in the keyed env; dispatch-over-TLS drill closed
  (ADR 0178); CHIMERA_ENTROPY_SIGNALS default-ON (ADR 0180). Harness
  findings 1–3 chipped (sentinel diff predicate, autocommit provenance).
- [ ] Graduate lexical routing v0 (ADRs 0165/0166) to embedding-based
  routing only once eval gating is in place.

## Overview
Chimera is a containerized, tools-capable agent built as a **chimera orchestrator** — a thin Python core that selectively pulls best-of-breed components from multiple agent SDKs, routes across OpenRouter + Anthropic models, and exposes a concentrically-expanding tool surface (shell → web → code-exec → MCP/sub-agents).

Four pillars:
- **Adaptability** — autoresearch lineage
- **Creativity** — claude-daemon (Reggio) + Leonardo
- **Functional ontology + drift** — KFM (Village + Agentic Evolution thesis), drift detection from autoresearch-unified
- **Environmental positioning** — Village

Sequence is **research-spike-first**: characterize and pick before we scaffold.

## Source Repositories

| Repo | Role |
|---|---|
| [elementalcollision/village](https://github.com/elementalcollision/village) | KFM logic, environmental positioning |
| [elementalcollision/Agentic_Evolution](https://github.com/elementalcollision/Agentic_Evolution) | Source thesis for KFM (functional ontology) |
| [elementalcollision/autoresearch-unified](https://github.com/elementalcollision/autoresearch-unified) | Drift detection logic, adaptability loops |
| [elementalcollision/claude-daemon](https://github.com/elementalcollision/claude-daemon) | Reggio driving logic, creativity |
| [elementalcollision/leonardo-daemon](https://github.com/elementalcollision/leonardo-daemon) | Creativity, embedding-driven novelty |
| [elementalcollision/xenocomm_sdk](https://github.com/elementalcollision/xenocomm_sdk) | A2A language — **future** consideration |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | Reference tools-capable agent |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | Reference tool layer |
| [mlcommons/croissant](https://github.com/mlcommons/croissant) | Data schema — candidate for ontology serialization |

Local clones already on disk: `framework_autoresearch`, `autoresearch-mlx`, `autoresearch_ARM`, `leonardo-uat-jina-v4`, `clawdbot`. GitHub CLI is authenticated for the elementalcollision org.

## Architecture Decisions

- **Chimera, not monoculture.** Thin orchestrator owns the agent loop; SDKs are pulled in as deep integrations only where they win. No single SDK is the spine.
- **Python core, TS only for UI/control plane.** Deferred until the core loop is stable.
- **OpenRouter + Anthropic only** for model access at MVP. One provider abstraction, two implementations.
- **Docker + docker-compose** runtime. Tools execute inside the same sandbox unless explicitly elevated.
- **Concentric tool surface.** Shell first. Each ring (web → code-exec → MCP/sub-agent) is its own phase with a verification gate.
- **Memory is deferred.** Phase 0 produces an ADR; no store is picked until ontology shape is known.
- **Ontology + drift is the riskiest piece.** It gets the prototype, not the scaffold.
- **Croissant evaluated as ontology serialization candidate** during Phase 0.
- **Xenocomm/A2A explicitly out of scope for v1** — noted for v2.

---

## Phase 0: Research Spike (Best-of-Breed Comparative Writeup)

**Goal:** Produce `docs/research/best-of-breed.md` — per pillar, the source repo, the specific pattern adopted, and rejected alternatives with rationale.

**Research playbook (applies to every Phase 0 task):**
- **Primary:** read source repos directly (git clones, `gh` for issues/PRs/discussions).
- **Library/API docs:** use **Context7** (`mcp__Context7__resolve-library-id` → `get-library-docs`) for any SDK, framework, or library referenced.
- **External literature & web:** use **Exa.ai** (`mcp__e3e02fce-...__web_search_exa`, `web_fetch_exa`) for papers, blog posts, and prior art — especially for KFM/ontology/drift academic background.
- **Ask the user** whenever a decision needs inspirational input the public web can't provide (internal context, taste, prior conversations). Bias toward asking over guessing.
- **Cite everything.** Every claim in a pillar writeup gets a citation: repo+path+commit, Context7 doc id, Exa result URL, or "per user (date)".

- [ ] **Task 0.1: Repo intake & scoping**
  - Clone all referenced repos into `research/_clones/`. One-paragraph "what it is, what it does well, what it ignores" per repo.
  - Files: `docs/research/repo-index.md`. Scope: S.

- [ ] **Task 0.2: Adaptability pillar (autoresearch-unified + local autoresearch variants)**
  - Extract patterns: environmental sensing, research loops, plan revision, drift-triggered re-planning.
  - Files: `docs/research/pillar-adaptability.md`. Scope: M.

- [ ] **Task 0.3: Creativity pillar (claude-daemon, leonardo-daemon, leonardo-uat-jina-v4)**
  - Patterns: divergent generation, critic loops, embedding-driven novelty, Reggio's driving logic.
  - Files: `docs/research/pillar-creativity.md`. Scope: M.

- [ ] **Task 0.4: Functional ontology + drift (Agentic_Evolution thesis, village/KFM, autoresearch-unified drift)** — RISKIEST
  - Reconstruct: ontology representation, drift detection signal, re-anchor mechanism.
  - Evaluate Croissant as a serialization candidate.
  - Files: `docs/research/pillar-ontology-drift.md`. Scope: L (split if needed).

- [ ] **Task 0.5: Environmental positioning (village)**
  - Patterns for agent-to-environment fit and repositioning.
  - Files: `docs/research/pillar-positioning.md`. Scope: S.

- [ ] **Task 0.6: Reference tool-layer survey (hermes-agent, openclaw, clawdbot)**
  - Tool schema, dispatch, sandbox boundary patterns.
  - Files: `docs/research/tool-layer-survey.md`. Scope: M.

- [ ] **Task 0.7: SDK chimera boundary ADR**
  - For each concern (planning, tool-use, routing, memory, eval): which SDK wins and why.
  - Files: `docs/adr/0001-sdk-chimera-boundaries.md`. Scope: M.

- [ ] **Task 0.8: Memory strategy ADR**
  - Driven by ontology shape from 0.4.
  - Files: `docs/adr/0002-memory-strategy.md`. Scope: S.

- [ ] **Task 0.9: Consolidated best-of-breed writeup**
  - Synthesizes 0.2–0.8 into the single deliverable.
  - Files: `docs/research/best-of-breed.md`. Scope: S.

### Checkpoint: Phase 0
- [ ] All pillar writeups cross-reference specific files/commits in source repos
- [ ] ADRs 0001 and 0002 committed
- [ ] **Human review and sign-off on `best-of-breed.md` before any code lands**

---

## Phase 1: Skeleton — Container + Orchestrator + Anthropic/OpenRouter + Shell

- [ ] **Task 1.1: Repo + Docker scaffold** — `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `Makefile`. Container starts, drops into the `chimera` CLI. Scope: S.
- [ ] **Task 1.2: Provider abstraction** — `chimera/providers/{base,anthropic,openrouter}.py`. One streaming chat interface. Scope: M.
- [ ] **Task 1.3: Agent loop v0** — Single-model, shell-only, no memory. think → call → observe → continue. Scope: M.
- [ ] **Task 1.4: Shell tool + sandbox boundary** — Strict allow-list; everything else requires explicit elevation flag. Scope: S.

### Checkpoint: Phase 1
- [ ] `docker compose run chimera "list /tmp and tell me what you see"` works on both providers
- [ ] Tests cover provider switching and shell allow-list

---

## Phase 2: Functional Ontology + Drift Prototype (de-risking core)

- [ ] **Task 2.1: Ontology data model** — Implement representation chosen in 0.4. Scope: M.
- [ ] **Task 2.2: Drift detector** — Detect when reasoning diverges from maintained ontology. Scope: M.
- [ ] **Task 2.3: Re-anchor loop** — On drift, agent revises plan/ontology before continuing. Scope: M.
- [ ] **Task 2.4: Memory backing (per ADR 0002)** — Wire in the chosen store. Scope: M.

### Checkpoint: Phase 2
- [ ] A scripted scenario forces drift; agent detects + re-anchors; transcript artifact saved
- [ ] Ontology persists across container restarts

---

## Phase 3: Tool Ring Expansion (concentric)

- [ ] **Task 3.1: Web fetch + web search** — autoresearch-style behavior. Scope: S.
- [ ] **Task 3.2: Sandboxed code execution (Python REPL in container)** — theorize/actualize. Scope: M.
- [ ] **Task 3.3: MCP client** — Mount arbitrary MCP servers from config. Scope: M.
- [ ] **Task 3.4: Sub-agent spawn (cross-model via OpenRouter)** — Specialist sub-agents on different models, orchestrator-coordinated. Scope: M.

### Checkpoint: Phase 3
- [ ] End-to-end: "research X, propose Y, prototype Y, summarize" using all four rings

---

## Phase 4: Adaptability + Creativity + Positioning Layers

- [ ] **Task 4.1: Adaptability layer** — Plan-revision loop from 0.2. Scope: M.
- [ ] **Task 4.2: Creativity layer** — Divergent-generation + critic from 0.3. Scope: M.
- [ ] **Task 4.3: Environmental positioning layer** — Agent senses container/env state and adjusts. Scope: M.

### Checkpoint: Phase 4 — v1 Complete
- [ ] All four pillars exercised by an integration scenario
- [ ] Human review for v1 sign-off

---

## Phase 5 (Optional, post-v1)

- [ ] **Task 5.1: TS control plane / dashboard** — observe transcripts, ontology state, drift events.
- [ ] **Task 5.2: Xenocomm / A2A integration spike** — explore agent-to-agent comms using xenocomm_sdk.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| KFM ontology pattern (Agentic_Evolution + village) doesn't reduce to a workable representation | High | Phase 0 Task 0.4 is the gate; if it fails, pause and re-scope before Phase 1 |
| Chimera SDK approach yields version/integration hell | Med | ADR 0001 codifies boundaries; pin versions; CI matrix per provider |
| OpenRouter latency/reliability hurts the loop | Med | Provider abstraction supports failover; Anthropic remains trusted-path default |
| Shell sandbox too loose | High | Strict allow-list by default; each new ring is its own phase with a boundary review |
| Memory choice gets re-litigated mid-build | Med | ADR 0002 locks decision at end of Phase 0; changes require follow-up ADR |
| Croissant proves wrong for ontology serialization | Low | It's evaluated, not assumed; ADR 0002 documents the choice either way |

## Open Questions
- API keys present in env (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`)? Preferred OpenRouter default models for routing?
- Should `research/_clones/` be gitignored, or do we vendor specific commits for reproducibility?
- Any constraints on the container base image (slim Python, Debian, distroless)?
