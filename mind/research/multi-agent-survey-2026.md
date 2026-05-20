# Multi-Agent Framework Survey — Mid-2026

> Compiled by Chimera. Sources: official docs, GitHub releases, named journalism, vendor blogs.
> Cutoff date for versions: ~2026-05-19.
> 10 frameworks/protocols surveyed with ≥ 2 cited sources each.

---

## 1. AG2 (formerly AutoGen) — The "AgentOS"

- **Version:** v0.11.3 (2026-03-16) | **First released:** forked from AutoGen November 2024; AutoGen originally September 2023
- **Org:** AG2 Community (forked from Microsoft AutoGen); PyPI: `ag2` / GitHub: `ag2ai/ag2` (~4.5K stars)
- **Model:** Conversation-driven multi-agent with `ConversableAgent`, group chats, tool-augmented agents. AG2 rebrands as "AgentOS" — a full operating system for agents with the "Universal Agent" concept.
- **Key differentiators:** Community fork that diverged from original AutoGen (which stayed with Microsoft). AG2 Beta emphasizes production-grade patterns: middleware, streaming, human-in-the-loop workflows, enhanced observability. Over 198 open issues — rapid iteration.
- **Sources:** [AG2 Blog — Beyond AutoGen](https://www.ag2.ai/blog/beyond-autogen) (2026-01-27); [AG2 Beta Motivation](https://docs.ag2.ai/latest/docs/beta/motivation/); [GitHub Releases](https://github.com/ag2ai/ag2/releases/tag/v0.11.3)

---

## 2. LangGraph — Graph-Based Agent Runtime

- **Version:** v1.2.0 (2026-05-12) | **v1.0 milestone:** 2025-10-22
- **Org:** LangChain; PyPI: `langgraph` / GitHub: `langchain-ai/langgraph` (~32K stars)
- **Model:** Low-level graph-based orchestration. Agents are stateful graphs of nodes (steps) and edges (transitions). Supports durable execution with checkpointing, human-in-the-loop breakpoints, and streaming. Separate from LangChain proper but interoperable.
- **Key differentiators:** Durable error-handler resume across host crashes (added v1.2.0). Built-in persistence / state management via `Checkpointer`. LangGraph Platform (GA) for deployment of long-running agents. Strong TypeScript support (`@langchain/langgraph` v1.3.0 npm, 2.3M weekly downloads). LangGraph is a "runtime" not a "prescription" — you design the graph.
- **Sources:** [LangChain + LangGraph 1.0 Blog](https://www.langchain.com/blog/langchain-langgraph-1dot0) (2025-10-22); [LangGraph v1.2.0 Release](https://github.com/langchain-ai/langgraph/releases/tag/1.2.0); [LangGraph Platform GA](https://blog.langchain.dev/langgraph-platform-ga)

---

## 3. CrewAI — Role-Playing Multi-Agent "Crews"

- **Version:** v1.14.5 (docs) / v1.14.3 (PyPI, 2026-05-18) | **Stable since:** ~2024
- **Org:** CrewAI Inc.; PyPI: `crewai` / GitHub: `crewAIInc/crewAI` (~52K stars)
- **Model:** Role-based agents assembled into "Crews" with sequential or hierarchical task execution. Defines agents with `role`, `goal`, `backstory`. Adds "Flows" for structured, event-driven pipelines. Integrates tools, memory, and MCP (Model Context Protocol) servers.
- **Key differentiators:** Very accessible, YAML/declarative configs (`agents.yaml`, `tasks.yaml`). Enterprise SaaS ("CrewAI AMP") on top of open-source core. Large community: 52K GitHub stars, active releases (~weekly). v1.14 deprecates old `Crew` constructor in favor of new patterns. Strong documentation with migration guides.
- **Sources:** [CrewAI Docs — Introduction](https://docs.crewai.com/en/introduction); [CrewAI v1.14.0 Release](https://github.com/crewAIInc/crewAI/releases/tag/1.14.0); [CrewAI Homepage](https://crewai.com/)

---

## 4. Magentic-One (Microsoft Agent Framework) — Orchestrator-Led Specialist Team

- **Version:** Microsoft Agent Framework v1.0 (2026-04-28) | Magentic-One paper: 2024-11-05
- **Org:** Microsoft Research → Microsoft Agent Framework; part of `agent-framework` Python/C# SDK on `learn.microsoft.com`
- **Model:** Generalist multi-agent system with an LLM-powered **Orchestrator** that dynamically plans, dispatches to specialists (WebSurfer, FileSurfer, Coder, ComputerTerminal), tracks progress, and replans. Hierarchical: Orchestrator delegates, specialists report back.
- **Key differentiators:** Battle-tested on benchmarks (GAIA, WebArena). Now integrated into the broader **Microsoft Agent Framework** (v1.0, open-source) which supports both single-agent patterns and Magentic orchestration. Python-first (C# support pending). The framework is a unified SDK spanning chat agents, tool-calling agents, and multi-agent Magentic workflows. A2A protocol interop supported.
- **Sources:** [Magentic-One — Microsoft Research](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/) (2024-11-05); [Microsoft Agent Framework 1.0](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/the-future-of-agentic-ai-inside-microsoft-agent-framework-1-0/4510698) (2026-04-28); [MS Learn — Magentic Orchestration](https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/orchestrations/magentic)

---

## 5. smolagents — Minimalist Code-Writing Agents

- **Version:** v1.24.0 (PyPI, current) | **First released:** 2024-12-31
- **Org:** Hugging Face; PyPI: `smolagents` / GitHub: `huggingface/smolagents` (~27K stars)
- **Model:** Agents that **write Python code** to call tools — not JSON function-calling. ~1,000 lines of core logic. Supports `CodeAgent` (code-actions), `ToolCallingAgent` (JSON), and multi-agent hierarchies where one agent orchestrates others.
- **Key differentiators:** Extreme simplicity — the "barebones" library. Code-as-action means agents can compose tools with loops, conditionals, and variables — more expressive than JSON function-calling. Deep Hugging Face Hub integration (free hosted models via Inference API). Multi-agent support via `ManagedAgent` pattern. Strong educational resource: Hugging Face Agents Course (unit 2).
- **Sources:** [Introducing smolagents](https://huggingface.co/blog/smolagents) (2024-12-31); [smolagents PyPI](https://pypi.org/project/smolagents/) (v1.24.0); [Multi-Agent Systems — HF Agents Course](https://huggingface.co/learn/agents-course/unit2/smolagents/multi_agent_systems)

---

## 6. OpenAI Agents SDK — Lightweight Multi-Agent Workflows

- **Version:** v0.17.3 (2026-05-19) | **First released:** ~March 2025 (as production upgrade from Swarm)
- **Org:** OpenAI; PyPI: `openai-agents` / GitHub: `openai/openai-agents-python` (~27K stars)
- **Model:** Lightweight framework with `Agent`, `Runner`, `handoff`, and `guardrails`. Agents can hand off control to other agents. Built-in tracing (OpenAI traces). Supports sandbox agents (code execution), text agents, and voice agents. Very few abstractions — designed to be simple.
- **Key differentiators:** Production upgrade from the experimental Swarm. April 2026 update added sandbox agents (inspect files, run commands, edit code, long-horizon tasks). ~1.4M daily PyPI downloads — massive adoption. v0.Y.Z versioning signals ongoing rapid evolution. TypeScript SDK also available (`@openai/agents`). Native OpenAI model integration, but model-agnostic at the protocol layer.
- **Sources:** [OpenAI Agents SDK Docs](https://openai.github.io/openai-agents-python/); [The Next Evolution of the Agents SDK](https://openai.com/index/the-next-evolution-of-the-agents-sdk/) (2026-04-15); [v0.17.3 Release](https://github.com/openai/openai-agents-python/releases/tag/v0.17.3)

---

## 7. Anthropic Agent SDK (Claude Code SDK) — Claude Code as a Library

- **Version:** v0.2.82 (Python, 2026-05-15) / TypeScript also available | **First released:** ~late 2025
- **Org:** Anthropic; PyPI: `claude-agent-sdk` / GitHub: `anthropics/claude-agent-sdk-python` (~7K stars)
- **Model:** Claude Code exposed as a programmable library. Agents get a full Claude Code session: file read/write, shell, MCP tools, sub-agent spawning, structured output. Built-in sandboxing and permission controls. "Build production AI agents with Claude Code as a library."
- **Key differentiators:** The agent *is* Claude Code — inherits all tool-use patterns, MCP server support, and the Claude reasoning loop. SDK is in Alpha/rapid development (v0.2.82). ~550K daily PyPI downloads. TypeScript SDK also available at `anthropics/claude-agent-sdk-typescript`. Teams can spawn sub-agents — multi-agent via hierarchical delegation. Tight coupling to Anthropic ecosystem but extremely capable within it.
- **Sources:** [Agent SDK Overview — Anthropic Docs](https://docs.anthropic.com/en/api/agent-sdk/overview); [GitHub: anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python); [v0.2.82 Release](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.82)

---

## 8. Google ADK (Agent Development Kit) — Enterprise Multi-Language Agent Framework

- **Version:** v2.0.0 GA (2026-05-19) | **First released:** ~April 2025 (v1.0); v1.0 across Python, TypeScript, Go, Java
- **Org:** Google; PyPI: `google-adk` / GitHub: `google/adk-python` (~20K stars)
- **Model:** Code-first agent toolkit for building, evaluating, and deploying agents. Supports multi-agent topologies, streaming, tools, memory, and artifact management. Ships in Python, TypeScript, Go, and Java. Integration with Google Cloud Agent Engine for deployment.
- **Key differentiators:** True polyglot (4 languages with parity). ADK 2.0 GA establishes production-grade foundations: evaluation framework, A2A protocol native integration, enterprise deployment on Google Cloud. Built-in support for Gemini and third-party models. Companion A2A protocol means ADK agents can interoperate with non-Google agents. Large internal Google usage plus external ecosystem.
- **Sources:** [ADK v2.0.0 Release](https://github.com/google/adk-python/releases/tag/v2.0.0) (2026-05-19); [What's New — ADK + Agent Engine + A2A](https://developers.googleblog.com/agents-adk-agent-engine-a2a-enhancements-google-io/) (2025-05-20); [ADK for Java 1.0.0](https://developers.googleblog.com/announcing-adk-for-java-100-building-the-future-of-ai-agents-in-java/) (2026-03-30)

---

## 9. A2A (Agent-to-Agent Protocol) — Cross-Vendor Interoperability Standard

- **Version:** Active development, Linux Foundation governed | **Announced:** 2025-04-09
- **Org:** Google (origin), now Linux Foundation; GitHub: `google/A2A` / `a2aproject/A2A` (~24K stars)
- **Model:** Open protocol (not a framework) for opaque agentic applications to discover, communicate, and collaborate. RESTful + JSON-RPC. Agent cards (discovery), task lifecycle management, streaming responses, multi-turn conversation support. Agents can be built in any framework and speak A2A.
- **Key differentiators:** Protocol, not framework — sits at the interoperability layer. Already adopted by Microsoft Agent Framework, Google ADK, LangGraph, and 50+ partners at launch. August 2025 upgrade brought complete developer toolkit on Google Cloud. April 2026 update added Agent Directory for discovery. Positioned as "HTTP for agents" — standard cross-framework communication. Strong enterprise focus.
- **Sources:** [Announcing A2A](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/) (2025-04-09); [A2A Protocol Upgrade](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade) (2025-08-01); [A2A Protocol Guide 2026](https://rapidclaw.dev/blog/a2a-protocol-complete-guide-2026); [GitHub: google/A2A](https://github.com/google/A2A)

---

## 10. OpenAI Swarm — Educational Multi-Agent Experiment (Legacy)

- **Version:** Archived (last commit 2025-03-11) | **First released:** 2024-10-15
- **Org:** OpenAI (Solutions team); GitHub: `openai/swarm` (~21K stars)
- **Model:** Lightweight, ergonomic multi-agent orchestration with `Agent` + `handoff` + `function-calling`. Designed as an educational/experimental showcase, not production. Superseded by OpenAI Agents SDK.
- **Key differentiators:** Historical significance — sparked the lightweight-agent-SDK pattern. README explicitly points users to the Agents SDK. Bare-minimum abstractions: agents, handoffs, context variables. Still studied for its design clarity but functionally deprecated.
- **Sources:** [GitHub: openai/swarm](https://github.com/openai/swarm); [Migration Guide: Swarm → Agents SDK](https://www.respan.ai/articles/openai-agents-sdk-vs-swarm)

---

## Summary Table

| Framework | Version | Date | Stars | Multi-Agent Model | Primary Lang |
|---|---|---|---|---|---|
| AG2 | v0.11.3 | 2026-03-16 | 4.5K | Conversation-driven group chat | Python |
| LangGraph | v1.2.0 | 2026-05-12 | 32K | Graph-based state machine | Python/TS |
| CrewAI | v1.14.x | 2026-05-18 | 52K | Role-based crews + flows | Python |
| Magentic-One / MS Agent Framework | v1.0 | 2026-04-28 | (part of MS) | Orchestrator + specialist team | Python (C# soon) |
| smolagents | v1.24.0 | 2026-05 | 27K | Code-writing agents + managed delegation | Python |
| OpenAI Agents SDK | v0.17.3 | 2026-05-19 | 27K | Handoff-based agent mesh | Python/TS |
| Anthropic Agent SDK | v0.2.82 | 2026-05-15 | 7K | Claude Code as library (sub-agents) | Python/TS |
| Google ADK | v2.0.0 GA | 2026-05-19 | 20K | Multi-agent topologies + A2A | Python/TS/Go/Java |
| A2A Protocol | — | (ongoing) | 24K | Cross-framework interop protocol | Protocol |
| OpenAI Swarm | archived | 2025-03 | 21K | Handoff-based (educational) | Python |
