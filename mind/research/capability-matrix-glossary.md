# Capability Matrix — Glossary of Terms

*Auto-generated from `mind/research/capability-matrix.html` (July 2026).  
Defines every capability axis and group-category term used in the Agent Framework Capability Matrix.  Intended as a stable reference for ADRs, research notes, and operator onboarding.*

---

## Group Categories

The 13 axes are organised into 5 groups.  Each group represents a **capability domain** — an area of agent-framework design that cuts across framework boundaries.

### Memory & State
How the framework stores, shares, and journals agent knowledge **beyond a single call or session**.

### Trust & Quality
Mechanisms that constrain agent autonomy, score proposal quality, and give the human operator a **structured veto or approval point**.

### Cost & Operations
Operational controls: **cost visibility**, tier-routing discipline, and protocol-level exposure of the agent to other systems.

### Context & Drift
Detecting when an agent's behaviour, vocabulary, or reasoning **changes over time** (drifts) — and anchoring it against known baselines.

### Multi-Agent Lifecycle
Capabilities that span agent **boundaries**: discovery of peers, federation into swarms, and spawning sub-agents across different model providers.

---

## Capability Axes

Each axis name matches a column header in the matrix exactly.  The definitions below are the canonical, shared understanding used when rating frameworks.

### 1. Cross-Agent Persistent Memory
**Group:** Memory & State

Persistent storage shared **across agent instances, threads, or runs** — not scoped to a single session.  Typically backed by a database (Postgres, SQLite) and optionally augmented with vector search.  A framework scores *first-class* when this is a built-in primitive (e.g. LangGraph's `Store` API), *partial* when it requires manual wiring, and *absent* when every agent silos state.

### 2. Swarm-KFM State
**Group:** Memory & State

A **shared-filesystem Knowledge File Manager (KFM)** primitive that allows a swarm of agents to read and write state through a common file tree.  Differs from Cross-Agent Persistent Memory in that the storage substrate is the **filesystem** (not a database), and the access pattern is **KFM-style** — keyed by path, human-inspectable, suitable for multi-agent coordination at the filesystem level.

> *KFM* = Knowledge File Manager — a pattern where agent state lives as plain files under a well-known directory root (`state/`, `mind/`), readable by any agent with filesystem access.

### 3. Chronicle / Journal
**Group:** Memory & State

A **structured, time-ordered record** of agent actions: execution timelines, tool calls, token usage, decisions, and produced artefacts.  More than a log — a chronicle is **queryable** and intended for later reflection, audit, and cross-agent awareness.  First-class implementations expose a journal API; partial implementations rely on external observability tools (e.g. LangSmith).

### 4. Trust Gating / Attestation
**Group:** Trust & Quality

The ability to **gate agent actions behind a trust verification step**.  This includes:

- **Attestation** — cryptographic proof that an action was produced by a known agent in a known state (e.g. ERC-8004 Trust Oracle, x402 attestations).
- **Trust gating** — refusing to execute high-impact actions unless the agent's trust score exceeds a threshold.
- In Chimera, this is the **ADR 0048** family — trust scores computed from proposer history, acceptance rates, and chronicle coherence, used to gate `create_mutation` and similar high-impact operations.

### 5. Proposer-Quality Scoring
**Group:** Trust & Quality

A real-time (inline) score assigned to **every proposal an agent makes** before the proposal reaches the operator.  The score estimates confidence that the proposal is *good* (useful, correct, non-redundant) and is used for **triage** — high-quality proposals get operator attention first.

- *First-class* means a built-in scoring pipeline at proposal-creation time.
- *Partial* means retrospective scoring only (e.g. Chimera's ADR 0090 acceptance-rate gate — judges after the operator acts, not before).
- *Absent* means no scoring at all (seven of eight surveyed frameworks).

Factors that feed a quality score: proposer's historical acceptance rate, novelty of the proposal vs chronicle history, complexity/diff-size of the proposed change.

### 6. Mutation Queue + Operator Gate
**Group:** Trust & Quality

A **structured queue of pending changes (mutations)** that the agent proposes and the **human operator must approve** before they are applied.  This is the canonical *human-in-the-loop* (HITL) mechanism.

- A *first-class* implementation provides: an interrupt primitive that pauses execution at any node, a durable mutation queue, and an operator approval/rejection interface (e.g. LangGraph's `interrupt()`, Chimera's `mutations` table + CLI gate).
- *Partial* means approval is possible but not a built-in queue primitive.
- *Absent* means no structured operator gate.

In Chimera: ADR 0041 governs the mutation queue; the operator sees proposals via `chimera proposals list` and approves/rejects them.

### 7. Cost Discipline (per-call / per-task)
**Group:** Cost & Operations

**Granular cost tracking and budgeting** — not just total spend, but per-call token counts, per-task cost attribution, and the ability to set **hard budgets** that stop execution when exceeded.

- *First-class*: built-in token tracking per run, configurable budgets (e.g. LangGraph Platform token budgets, Chimera's per-call cost attribution + adaptive budgets from ADR 0028).
- *Partial*: cost data is available but requires manual aggregation or external tooling.
- *Absent*: no cost visibility.

### 8. Tier Escalation Across Providers
**Group:** Cost & Operations

The ability to **route a task to a different model tier or provider** based on task complexity, failure, or cost constraints — automatically, not manually.  For example: try `haiku` first; if confidence is low, escalate to `sonnet`; if still failing, escalate to `opus`.

- *First-class*: built-in tier-routing engine with configurable escalation policies (Chimera's provider tier escalation).
- *Partial*: manual model-switching nodes.
- *Absent*: single-model, single-provider only.

### 9. MCP Server-Side Exposure
**Group:** Cost & Operations

**Exposing the agent itself as an MCP (Model Context Protocol) server** so that other agents — possibly from different frameworks — can call its tools, read its resources, and interact with it as a peer.

- *First-class*: the agent can serve an MCP endpoint natively.
- *Partial*: MCP exposure requires adapters or wrappers.
- *Absent*: the agent cannot be addressed via MCP.

### 10. Drift / Anchor Primitives
**Group:** Context & Drift

Mechanisms that **detect when an agent's behaviour, output style, vocabulary, or reasoning quality changes over time** — and **anchor** it against a known baseline (the "anchor") so that drift can be measured.

- *Drift* is the gradual un-anchoring of agent behaviour from its intended specification.  It manifests as: vocabulary shifts ("ghost lexicon"), semantic changes in how the agent describes its own outputs, or behavioural changes (different tool-use patterns for the same tasks).
- *Anchor primitives* are the stable reference points — e.g. a snapshot of word-frequency distributions, expected tool-call signatures, or chronicle patterns — against which current behaviour is compared.
- In Chimera: ADR 0089 provides signal-density gating and drift-detection instruments (ghost-lexicon, semantic-drift, behavioural-footprint scorers) that fire when composite drift exceeds a threshold.

No surveyed framework has first-class drift/anchor primitives.  Chimera is the only partial.

### 11. Signal-Density Gating
**Group:** Context & Drift

A **context-management strategy** that gates based on the **information density** of signals in the agent's context window — not just token count.  When signal density drops below a threshold (too much filler, too little information per token), the agent compresses, summarises, or truncates context to restore density.

- Differs from naive context-overflow handling (which summarises blindly when the token limit is hit).
- A *first-class* implementation measures density continuously and applies compression proactively.
- In Chimera: this is the primary drift-prevention mechanism — signal-density gating prevents the context window from filling with low-signal filler that masks genuine drift.

### 12. Peer Discovery & Federation
**Group:** Multi-Agent Lifecycle

The ability for agents to **discover each other** (without hard-coded addresses) and **federate** into a cooperating multi-agent system.

- *First-class*: native decentralised discovery, agent registry, or announcement protocol (e.g. Google ADK's agent discovery).
- *Partial*: discovery via a central platform deployment, not a peer-to-peer mechanism.
- *Absent*: agents must be manually wired together.

### 13. Sub-Agent Spawn Across Providers
**Group:** Multi-Agent Lifecycle

The ability to **spawn a sub-agent** (a child agent with its own context and tool surface) that runs on a **different model provider** from the parent.  This is the `spawn_sub_agent` primitive in Chimera, which can target `haiku`, `sonnet`, or `opus` tiers across Anthropic and OpenRouter providers.

- *First-class*: built-in sub-agent spawn with cross-provider model selection.
- *Partial*: sub-agents possible but locked to the same provider as the parent.
- *Absent*: no sub-agent spawning primitive.

---

## Supporting Terms (Chimera-Internal)

These terms appear in the ADR and research corpus but are not matrix axes.  They are included here because they are frequently referenced alongside the matrix capabilities.

### ADR
**Architecture Decision Record.**  A numbered, dated, immutable document in `mind/adr/` that records a design decision, its rationale, and its consequences.  ADRs form the backbone of Chimera's institutional memory.

### Proposer
A subsystem or observation engine that **emits proposals** (mutations, task splits, config changes).  Examples: the chronicle-reflection engine, the curiosity engine, the morning strategic planner.  Each proposer has a tracked acceptance rate (ADR 0090).

### Mutation
A **proposed change to the running system** — a new skill, a task split, a config change, an ADR, etc.  Mutations are enqueued, scored, and await operator approval before application (ADR 0041, ADR 0090).

### Proposal Types
- **`skill_proposal`** — propose a new agent skill or capability.
- **`task_split`** — propose splitting a large task into smaller sub-tasks.
- **`config_change`** — propose a configuration change (model tier, budget, gating threshold, etc.).

### Acceptance Rate
The **rolling ratio of accepted to total proposals** for a given proposer type, tracked over a configurable window.  Proposers whose acceptance rate drops below a degradation threshold are auto-degraded (their proposals are suppressed or flagged).  ADR 0090.

### Ghost Lexicon
A **drift-detection instrument** that compares the current observed vocabulary distribution against the anchor snapshot.  Words that appear in observation but not in the anchor are "ghost words"; a high ghost-lexicon score indicates vocabulary drift.  Stored in `state/drift/current.json`.

### Signal Density
The ratio of **information-bearing content to total token count** in an agent's context window or output.  Low signal density triggers proactive compression or truncation.  Measured by the signal-density gating instrument (ADR 0089, ADR 0102).

### Chronicle
The structured, time-ordered journal of agent actions, decisions, and artefacts.  Stored as timestamped entries in `mind/chronicle/`.  Used by proposers for reflection, by drift instruments for baseline comparison, and by the operator for audit.

### Operator Gate
The **human approval checkpoint** in the mutation pipeline.  The operator reviews enqueued mutations (via CLI or dashboard) and explicitly approves or rejects each one before it takes effect.

### Anchor
A **snapshot of expected/stable behaviour** used as the reference point for drift detection.  Anchors are captured during stable operation (after a "boundary marked" event) and stored in `state/drift/current.json` as `anchor_words` and `anchor_tools`.

---

## Framework Abbreviations

| Abbreviation | Full Name |
|---|---|
| LangGraph | LangGraph (LangChain) |
| CrewAI | CrewAI (CrewAI Inc.) |
| AutoGen | AutoGen (Microsoft) |
| OpenAI Agents SDK | OpenAI Agents SDK (OpenAI) |
| OpenClaw | OpenClaw (OpenClaw) |
| Google ADK | Google Agent Development Kit (Google) |
| Mastra | Mastra (Gatsby Team) |
| Chimera | Chimera (Multi-LLM / Chimera) |

---

## Rating Legend

| Symbol | Meaning |
|---|---|
| ✓ | First-class / built-in |
| ~ | Partial / plugin / DIY |
| ✗ | Not available |

---

*Generated by Chimera research on 2026-07-20.  Source matrix: `mind/research/capability-matrix.html`.*
