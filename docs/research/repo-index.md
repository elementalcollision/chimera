# Repo Index — Chimera Phase 0 Research Spike

Generated: 2026-05-18
Source clones: `research/_clones/` (gitignored)

## elementalcollision/village

A mature, production-running multi-agent civilization simulator built on XenoComm SDK and the KFM Protocol (Kill/Fuck/Marry lifecycle operators). Currently running 24 containers on Mac Mini with real LLM calls, 15-min cycles, monitoring infrastructure (Prometheus/Grafana/Tempo). Stands out for its agonistic-futures architecture—conflict as constitutive rather than failure—and explicit operator lifecycle management via `agents/`, `contracts/`, and `schemas/` (see `libs/kfm_core.py` equivalent patterns). Weak spots: deeply domain-specific (village metaphor), limited public documentation on the core KFM implementation, and tightly coupled to its own infrastructure (OrbStack deployment). Port the operator lifecycle model and resilience patterns; leave the civilization simulation specifics.

## elementalcollision/Agentic_Evolution

A theoretical thesis (document-heavy, 350+ pages) exploring the KFM game as a phenomenological framework for selection dynamics in digital ecosystems. This is the foundational ontology behind village—it structures how agents are managed, mutated, and deprecated. The paper is meticulously reasoned but not directly executable; it establishes the vocabulary and conceptual machinery that village, leonardo-daemon, and claude-daemon operationalize. Adopt the tripartite selection model (Kill/Fuck/Marry mapping to Eliminate/Adapt/Integrate); reject the paper's academic scope for Chimera's engineering needs.

## elementalcollision/autoresearch-unified

A platform-agnostic autonomous experiment loop where Claude proposes hyperparameter changes, trains GPT-2 for 5 minutes, evaluates val_bpb, and loops—running across NVIDIA/AMD/Intel/Apple hardware with unified orchestration. Standout: `tui/orchestrator.py` (core loop), `tui/llm_backend.py` (Claude API integration), `backends/registry.py` (pluggable platform detection), and `tui/resilience.py` (heartbeat, signal handlers, PID locks). The unified backend pattern—platform-specific scripts + shared orchestration layer—is excellent for Chimera's multi-model routing. Weak spot: narrowly scoped to training; not a general-purpose agent framework.

## elementalcollision/claude-daemon

Reggio driving logic for Leonardo—a heartbeat-based daemon writing cycle observations to a git-backed journal (leonardo-forge). README empty; code reveals: `daemon/` (cycle loop), `memory/` (observation indexing), `mind/` (decision logic), `safeguards/` (safety layer), `tools/` (Claude tool integrations). Architecture: observe → reason → act → commit cycle with creativity scheduling. Patterns worth pulling: the heartbeat loop model, tool integration harness, and mind/safeguards separation. Limitation: tightly bound to leonardo's specific neuroscience-inspired modes; generalize the daemon pattern for Chimera.

## elementalcollision/leonardo-daemon

Leonardo-specific evolution of claude-daemon with 6-mode + contemplation scheduler, Jina v4 multimodal embeddings, dual named-vector retrieval (BGE-M3 + Jina), and Faith state machinery (emergent behavioral tracking). Skeleton sprint (L1 phase); heartbeat path works, cognitive modes defer to L2. See `daemon/` + `memory/` for emerging patterns around model-tier routing and creativity scheduling. Key difference from claude-daemon: embedding-driven novelty detection and asymmetric mode weighting. Extract the model-routing abstraction; the Faith machinery is pre-alpha.

## elementalcollision/xenocomm_sdk

High-performance A2A (agent-to-agent) communication framework with MCP Protocol Bridge, now with 40+ tools for alignment verification, protocol negotiation, and emergence management. C++ core + Python bindings + MCP server. Strengths: capability signaling (efficient binary encoding), formal alignment strategies (5 strategies: knowledge, goals, terminology, assumptions, context—see `extensions/common_ground/` for strategy builder), and EmergenceManager for safe protocol evolution (canary deployments, rollback). The alignment verification framework is directly adoptable for Chimera multi-LLM coordination. Weak: primarily network/protocol; doesn't address single-process multi-model orchestration.

## NousResearch/hermes-agent

Reference implementation of a production-ready tools-capable agent with closed learning loop (periodic nudges, autonomous skill creation, FTS5 session search), scheduled automations (cron), multi-platform messaging gateway (Telegram, Discord, Slack, WhatsApp, Signal), and parallel subagent spawning via RPC. Standout patterns: `agent/` (core loop), `skills/` (agentskills.io standard), `memory/` (procedural memory with user profiles), `tools/` (40+ tools), and `gateway/` (platform abstraction). The skill system and user modeling (Honcho dialectic) are production-grade. Limitation: monolithic agent design; not architected for multi-LLM orchestration—useful reference but not directly adaptable.

## openclaw

Predecessor to hermes-agent; personal AI assistant for single user, multi-channel (WhatsApp, Telegram, Slack, Discord, etc.). Node.js + TypeScript frontend + backend with Canvas rendering, real-time TUI, and skill plugins. Strengths: gateway architecture decoupling control plane from product (see `packages/`, `gateway/`, `src/` structure), and canvas/rendering primitives. Weakness: single-agent, single-LLM design; messaging-focused rather than tool-orchestrated; framework is older and less polished than hermes. Use as architectural reference for channel multiplexing; not a tool-calling reference.

## mlcommons/croissant

JSON-LD metadata format for ML datasets combining metadata, resource descriptions, data structure, and ML semantics into a single file. Built on schema.org Dataset vocabulary; integrates with Google Datasets Search, Kaggle, HuggingFace, TensorFlow, OpenML, Dataverse, and CKAN. Standout: RecordSet abstraction for data structure, field type mappings, and responsible-AI metadata. Weak: domain-specific to dataset provenance and discovery; not directly relevant to agent orchestration. Consider for ontology serialization if Chimera needs to broadcast capability schemas; croissant itself is not an agent framework.

---

## Summary

**Strong Adoption Candidates (copy patterns):**
- `autoresearch-unified`: Multi-platform orchestration registry & unified backend pattern
- `xenocomm_sdk`: Alignment verification strategies & protocol negotiation state machines
- `village`: KFM operator lifecycle & resilience (heartbeat, signal handlers)
- `hermes-agent`: Skill system, multi-platform gateway, memory abstractions

**Theoretical Foundation:**
- `Agentic_Evolution`: KFM ontology (Kill/Fuck/Marry → Eliminate/Adapt/Integrate)

**Reference Implementations (architecture, not code reuse):**
- `leonardo-daemon`: Model-tier routing & embedding-driven novelty
- `claude-daemon`: Daemon heartbeat loop
- `openclaw`: Gateway multiplexing pattern

**Out of Scope:**
- `croissant`: Dataset metadata (may revisit for ontology layer)

Total estimated scope: 1200 lines of adaptive patterns + 80 lines of KFM ontology → ~0.8 person-weeks for pillar extraction (Tasks 0.2–0.6).

